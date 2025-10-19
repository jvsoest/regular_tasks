#!/usr/bin/env python3
"""
IMAP Inbox Migrator with Safety Mode

- Copies all messages from a source IMAP mailbox (default: INBOX) to a destination mailbox.
- Preserves FLAGS and INTERNALDATE.
- Optional deduplication using Message-ID (recommended).
- Optional 'move' behavior: delete messages from source only after verified migration.
- Safety mode: retry + verify on destination before deletion.

Usage:
    python imap_inbox_migrator.py /path/to/config.yaml
"""

import sys
import ssl
import time
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    print("Missing dependency: pyyaml. Install with: pip install pyyaml")
    raise

try:
    from imapclient import IMAPClient
except ImportError:
    print("Missing dependency: imapclient. Install with: pip install imapclient")
    raise


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Defaults
    cfg.setdefault("source", {})
    cfg.setdefault("dest", {})
    cfg.setdefault("options", {})
    cfg["source"].setdefault("mailbox", "INBOX")
    cfg["dest"].setdefault("mailbox", "INBOX")
    o = cfg["options"]
    o.setdefault("batch_size", 200)
    o.setdefault("dedupe_by", "message_id")  # message_id | none
    o.setdefault("create_dest_mailbox", True)
    o.setdefault("search_query", "ALL")
    o.setdefault("idle_delay_sec", 0)
    # Move/safety options
    o.setdefault("delete_after_copy", False)
    o.setdefault("safety_mode", True)               # enable safe move by default
    o.setdefault("verify_strategy", "message_id")   # message_id | none
    o.setdefault("max_retries", 3)
    o.setdefault("retry_backoff_sec", 2.0)          # base backoff
    return cfg


def connect_imap(
    host: str,
    port: Optional[int],
    username: str,
    password: str,
    use_ssl: bool = True,
    starttls: bool = False,
    ssl_verify: bool = True,
) -> IMAPClient:
    ssl_context = None
    if use_ssl or starttls:
        ssl_context = ssl.create_default_context()
        if not ssl_verify:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

    if use_ssl:
        client = IMAPClient(host, port=port or 993, ssl=True, ssl_context=ssl_context)
    else:
        client = IMAPClient(host, port=port or 143, ssl=False)

    if starttls and not use_ssl:
        client.starttls(ssl_context=ssl_context)

    client.login(username, password)
    return client


def ensure_mailbox(client: IMAPClient, mailbox: str):
    try:
        client.select_folder(mailbox, readonly=False)
    except Exception:
        client.create_folder(mailbox)
        client.select_folder(mailbox, readonly=False)


def chunked(seq: List[int], size: int) -> Iterable[List[int]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def normalize_internaldate(dt) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def build_dest_messageid_index(
    dest: IMAPClient, mailbox: str, limit: Optional[int] = None
) -> Set[str]:
    dest.select_folder(mailbox, readonly=True)
    uids = dest.search(["ALL"])
    if limit is not None:
        uids = uids[:limit]
    existing: Set[str] = set()
    if not uids:
        return existing

    to_fetch = ["BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"]
    for batch in chunked(uids, 500):
        resp = dest.fetch(batch, to_fetch)
        for _, data in resp.items():
            hdr_bytes = data.get(b"BODY[HEADER.FIELDS (MESSAGE-ID)]") or data.get(
                b"BODY[HEADER.FIELDS (MESSAGE-ID)]".lower()
            )
            if not hdr_bytes:
                continue
            try:
                text = hdr_bytes.decode(errors="replace")
                for line in text.splitlines():
                    if line.lower().startswith("message-id:"):
                        msgid = line.split(":", 1)[1].strip()
                        if msgid:
                            existing.add(msgid.strip())
                        break
            except Exception:
                continue
    return existing


def extract_message_id(header_bytes: Optional[bytes]) -> Optional[str]:
    if not header_bytes:
        return None
    text = header_bytes.decode(errors="replace")
    for line in text.splitlines():
        if line.lower().startswith("message-id:"):
            return line.split(":", 1)[1].strip()
    return None


def append_with_retries(
    dst: IMAPClient,
    mailbox: str,
    raw_msg: bytes,
    flags: Tuple[bytes, ...],
    msg_time: datetime,
    max_retries: int,
    backoff_sec: float,
) -> bool:
    """
    Append a message with retry + exponential backoff.
    Returns True on success, False if all retries failed.
    """
    attempt = 0
    delay = backoff_sec
    while True:
        try:
            # IMAPClient.append returns APPENDUID (if UIDPLUS is supported) or None.
            dst.append(mailbox, raw_msg, flags=flags, msg_time=msg_time)
            return True
        except Exception as e:
            attempt += 1
            if attempt > max_retries:
                print(f"[ERROR] Append failed after {max_retries} retries: {e}")
                return False
            print(f"[WARN] Append failed (attempt {attempt}/{max_retries}): {e}. Retrying in {delay:.1f}s…")
            time.sleep(delay)
            delay *= 2  # backoff


def verify_on_destination(
    dst: IMAPClient,
    mailbox: str,
    msgid: Optional[str],
    verify_strategy: str,
) -> bool:
    """
    Returns True if the message is confirmed present on destination.
    For 'message_id', we search by Message-ID.
    For 'none', we assume success (not recommended if deleting).
    """
    if verify_strategy == "none":
        return True
    if verify_strategy == "message_id":
        if not msgid:
            # No Message-ID; cannot verify safely
            return False
        try:
            dst.select_folder(mailbox, readonly=True)
            # SEARCH HEADER "Message-ID" "<id>"
            matches = dst.search(["HEADER", "Message-ID", msgid])
            return len(matches) > 0
        except Exception as e:
            print(f"[WARN] Verification search failed: {e}")
            return False
    # Unknown strategy -> be conservative
    return False


def filter_flags_for_unread(flags: Tuple[bytes, ...]) -> Tuple[bytes, ...]:
    """
    Remove the \Seen flag to ensure messages are marked as unread in destination.
    """
    return tuple(flag for flag in flags if flag.lower() != b'\\seen')


def migrate(cfg: Dict[str, Any]) -> None:
    src_cfg = cfg["source"]
    dst_cfg = cfg["dest"]
    opts = cfg["options"]

    print("Connecting to source…")
    src = connect_imap(
        host=src_cfg["host"],
        port=src_cfg.get("port"),
        username=src_cfg["username"],
        password=src_cfg["password"],
        use_ssl=src_cfg.get("ssl", True),
        starttls=src_cfg.get("starttls", False),
        ssl_verify=src_cfg.get("ssl_verify", True),
    )
    print("Connecting to destination…")
    dst = connect_imap(
        host=dst_cfg["host"],
        port=dst_cfg.get("port"),
        username=dst_cfg["username"],
        password=dst_cfg["password"],
        use_ssl=dst_cfg.get("ssl", True),
        starttls=dst_cfg.get("starttls", False),
        ssl_verify=dst_cfg.get("ssl_verify", True),
    )

    src_mailbox = src_cfg.get("mailbox", "INBOX")
    dst_mailbox = dst_cfg.get("mailbox", "INBOX")

    if opts.get("create_dest_mailbox", True):
        ensure_mailbox(dst, dst_mailbox)

    print(f"Selecting source mailbox: {src_mailbox}")
    src.select_folder(src_mailbox, readonly=False)
    print(f"Selecting dest mailbox: {dst_mailbox}")
    dst.select_folder(dst_mailbox, readonly=False)

    print("Listing source messages…")
    query = opts.get("search_query", "ALL")
    search_criteria = query if isinstance(query, list) else [query]
    src_uids: List[int] = src.search(search_criteria)
    print(f"Found {len(src_uids)} messages to consider.")

    dedupe_by = (opts.get("dedupe_by") or "message_id").lower()
    dest_message_ids: Set[str] = set()
    if dedupe_by == "message_id":
        print("Building destination Message-ID index (this can take a while for large mailboxes)…")
        dest_message_ids = build_dest_messageid_index(dst, dst_mailbox)
        print(f"Indexed {len(dest_message_ids)} Message-IDs in destination.")

    batch_size = int(opts.get("batch_size", 200))
    idle_delay = float(opts.get("idle_delay_sec", 0))
    delete_after_copy = bool(opts.get("delete_after_copy", False))
    safety_mode = bool(opts.get("safety_mode", True))
    verify_strategy = (opts.get("verify_strategy") or "message_id").lower()
    max_retries = int(opts.get("max_retries", 3))
    backoff_sec = float(opts.get("retry_backoff_sec", 2.0))

    fetch_items = [
        b"RFC822",  # full raw message
        b"FLAGS",
        b"INTERNALDATE",
        b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]",
    ]

    migrated = 0
    skipped = 0
    # Only delete messages we *know* are safely on destination:
    uids_to_delete: List[int] = []

    for batch in chunked(src_uids, batch_size):
        resp = src.fetch(batch, fetch_items)
        for uid in batch:
            data = resp.get(uid)
            if not data:
                continue

            raw_msg: bytes = data.get(b"RFC822", b"")
            flags = data.get(b"FLAGS", ())
            internaldate = normalize_internaldate(data.get(b"INTERNALDATE", None))

            # Extract Message-ID for dedupe + verification
            msgid = extract_message_id(
                data.get(b"BODY[HEADER.FIELDS (MESSAGE-ID)]")
                or data.get(b"BODY[HEADER.FIELDS (MESSAGE-ID)]".lower())
            )

            # Deduping
            if dedupe_by == "message_id" and msgid and msgid in dest_message_ids:
                skipped += 1
                continue

            # Filter flags to mark as unread in destination
            unread_flags = filter_flags_for_unread(flags)

            # Append with retry
            ok = append_with_retries(
                dst, dst_mailbox, raw_msg, unread_flags, internaldate, max_retries, backoff_sec
            )
            if not ok:
                # Do not mark for deletion
                continue

            # Update in-memory index (avoid re-copy within same run)
            if msgid:
                dest_message_ids.add(msgid)

            migrated += 1

            # Decide whether to delete this UID
            if delete_after_copy:
                if safety_mode:
                    verified = verify_on_destination(dst, dst_mailbox, msgid, verify_strategy)
                    if verified:
                        uids_to_delete.append(uid)
                    else:
                        print(f"[INFO] Skipping deletion for UID {uid}: verification not confirmed.")
                else:
                    uids_to_delete.append(uid)

            if idle_delay > 0:
                time.sleep(idle_delay)

        print(f"Progress: migrated {migrated}, skipped {skipped} of {len(src_uids)} total…")

    # Delete only verified UIDs (or all migrated if safety_mode is off)
    if delete_after_copy and uids_to_delete:
        print(f"Deleting {len(uids_to_delete)} source messages…")
        try:
            src.add_flags(uids_to_delete, [b"\\Deleted"])
            src.expunge()
        except Exception as e:
            print(f"[ERROR] Failed to delete/expunge on source: {e}")

    print("\nDone.")
    print(f"Migrated: {migrated}")
    print(f"Skipped (dedupe): {skipped}")
    if delete_after_copy:
        print(f"Deleted from source: {len(uids_to_delete)} (safety_mode={'on' if safety_mode else 'off'})")

    src.logout()
    dst.logout()


def main():
    if len(sys.argv) != 2:
        print("Usage: python imap_inbox_migrator.py /path/to/config.yaml")
        sys.exit(1)
    cfg_path = sys.argv[1]
    cfg = load_config(cfg_path)
    migrate(cfg)


if __name__ == "__main__":
    main()