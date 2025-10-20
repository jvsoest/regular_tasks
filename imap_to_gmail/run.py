#!/usr/bin/env python3
"""
IMAP to Gmail API Import

Reads emails from an IMAP server and imports them into Gmail using the
Gmail API's messages.import endpoint, which preserves email metadata
and is more efficient than IMAP append.

Features:
- Reads messages from any IMAP server
- Uses Gmail API import (not IMAP) for destination
- Preserves message properties and internal date
- Optional deduplication using Message-ID
- Optional 'move' behavior: delete from source after verified import
- Safety mode: verify on Gmail before deletion
- OAuth2 authentication for Gmail API

Requirements:
    pip install pyyaml imapclient google-auth-oauthlib google-auth-httplib2 google-api-python-client

Usage:
    python run.py /path/to/config.yaml
"""

import sys
import ssl
import time
import base64
import os.path
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

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("Missing Google API dependencies. Install with:")
    print("pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    raise


# Gmail API scopes - we need full Gmail access for importing
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']


def load_config(path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    
    # Defaults
    cfg.setdefault("source", {})
    cfg.setdefault("gmail", {})
    cfg.setdefault("options", {})
    
    cfg["source"].setdefault("mailbox", "INBOX")
    cfg["gmail"].setdefault("credentials_file", "credentials.json")
    cfg["gmail"].setdefault("token_file", "token.json")
    cfg["gmail"].setdefault("user_id", "me")
    
    o = cfg["options"]
    o.setdefault("batch_size", 100)
    o.setdefault("dedupe_by", "message_id")
    o.setdefault("search_query", "ALL")
    o.setdefault("idle_delay_sec", 0)
    o.setdefault("delete_after_import", False)
    o.setdefault("safety_mode", True)
    o.setdefault("max_retries", 3)
    o.setdefault("retry_backoff_sec", 2.0)
    o.setdefault("gmail_labels", [])
    o.setdefault("mark_as_unread", True)
    
    return cfg


def get_gmail_service(credentials_file: str, token_file: str):
    """
    Authenticate and return a Gmail API service instance.
    
    Uses OAuth2 with a credentials file from Google Cloud Console.
    Token is cached for subsequent runs.
    """
    creds = None
    
    # Token file stores the user's access and refresh tokens
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    
    service = build('gmail', 'v1', credentials=creds)
    return service


def connect_imap(
    host: str,
    port: Optional[int],
    username: str,
    password: str,
    use_ssl: bool = True,
    starttls: bool = False,
    ssl_verify: bool = True,
) -> IMAPClient:
    """Connect to IMAP server."""
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


def chunked(seq: List[int], size: int) -> Iterable[List[int]]:
    """Split a list into chunks."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def extract_message_id(header_bytes: Optional[bytes]) -> Optional[str]:
    """Extract Message-ID from email headers."""
    if not header_bytes:
        return None
    text = header_bytes.decode(errors="replace")
    for line in text.splitlines():
        if line.lower().startswith("message-id:"):
            return line.split(":", 1)[1].strip()
    return None


def build_gmail_messageid_index(service, user_id: str = 'me') -> Set[str]:
    """
    Build an index of Message-IDs already in Gmail.
    
    Note: This can be slow for large mailboxes. Gmail API doesn't provide
    a direct way to search by Message-ID header, so we need to fetch headers.
    """
    print("Building Gmail Message-ID index (this may take a while)...")
    existing: Set[str] = set()
    
    try:
        page_token = None
        while True:
            results = service.users().messages().list(
                userId=user_id,
                maxResults=500,
                pageToken=page_token
            ).execute()
            
            messages = results.get('messages', [])
            if not messages:
                break
            
            # Fetch headers for each message
            for msg in messages:
                try:
                    msg_data = service.users().messages().get(
                        userId=user_id,
                        id=msg['id'],
                        format='metadata',
                        metadataHeaders=['Message-ID']
                    ).execute()
                    
                    headers = msg_data.get('payload', {}).get('headers', [])
                    for header in headers:
                        if header['name'].lower() == 'message-id':
                            msgid = header['value'].strip()
                            if msgid:
                                existing.add(msgid)
                            break
                except HttpError as e:
                    print(f"[WARN] Error fetching message {msg['id']}: {e}")
                    continue
            
            page_token = results.get('nextPageToken')
            if not page_token:
                break
            
            print(f"Indexed {len(existing)} messages so far...")
    
    except HttpError as e:
        print(f"[ERROR] Failed to build Gmail index: {e}")
    
    return existing


def import_to_gmail_with_retries(
    service,
    user_id: str,
    raw_msg: bytes,
    labels: List[str],
    mark_as_unread: bool,
    max_retries: int,
    backoff_sec: float,
) -> Optional[str]:
    """
    Import a message to Gmail using the messages.import endpoint.
    
    Returns the Gmail message ID on success, None on failure.
    """
    # Encode message in base64url format as required by Gmail API
    encoded_message = base64.urlsafe_b64encode(raw_msg).decode('utf-8')
    
    # Build the request body
    body = {
        'raw': encoded_message,
    }
    
    # Add labels if specified
    if labels:
        body['labelIds'] = labels
    
    # Handle unread flag
    if mark_as_unread:
        # Don't include UNREAD label - the internalDateSource will preserve original state
        # We'll modify it after import
        pass
    
    attempt = 0
    delay = backoff_sec
    
    while True:
        try:
            # Use messages.import to preserve internal date and other metadata
            result = service.users().messages().import_(
                userId=user_id,
                body=body,
                internalDateSource='dateHeader',  # Preserve original date
                neverMarkSpam=True,               # Don't automatically mark as spam
                processForCalendar=False          # Don't process calendar invites
            ).execute()
            
            msg_id = result.get('id')
            
            # If we want to mark as unread, remove the UNREAD label was added or modify
            if mark_as_unread and msg_id:
                try:
                    # Remove UNREAD from labelIds to mark as unread
                    service.users().messages().modify(
                        userId=user_id,
                        id=msg_id,
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                except HttpError:
                    # If it fails, that's okay - message is still imported
                    pass
            
            return msg_id
            
        except HttpError as e:
            attempt += 1
            if attempt > max_retries:
                print(f"[ERROR] Import failed after {max_retries} retries: {e}")
                return None
            
            print(f"[WARN] Import failed (attempt {attempt}/{max_retries}): {e}. Retrying in {delay:.1f}s…")
            time.sleep(delay)
            delay *= 2  # Exponential backoff
        except Exception as e:
            attempt += 1
            if attempt > max_retries:
                print(f"[ERROR] Unexpected error after {max_retries} retries: {e}")
                return None
            
            print(f"[WARN] Unexpected error (attempt {attempt}/{max_retries}): {e}. Retrying in {delay:.1f}s…")
            time.sleep(delay)
            delay *= 2


def verify_on_gmail(service, user_id: str, msgid: Optional[str]) -> bool:
    """
    Verify that a message with the given Message-ID exists in Gmail.
    
    Returns True if found, False otherwise.
    """
    if not msgid:
        return False
    
    try:
        # Search for the message by Message-ID
        # Gmail search uses rfc822msgid: prefix for Message-ID header
        query = f'rfc822msgid:{msgid}'
        results = service.users().messages().list(
            userId=user_id,
            q=query,
            maxResults=1
        ).execute()
        
        messages = results.get('messages', [])
        return len(messages) > 0
        
    except HttpError as e:
        print(f"[WARN] Verification search failed: {e}")
        return False


def migrate(cfg: Dict[str, Any]) -> None:
    """Main migration function."""
    src_cfg = cfg["source"]
    gmail_cfg = cfg["gmail"]
    opts = cfg["options"]

    print("Connecting to Gmail API…")
    gmail_service = get_gmail_service(
        gmail_cfg["credentials_file"],
        gmail_cfg["token_file"]
    )
    user_id = gmail_cfg.get("user_id", "me")
    
    print("Connecting to source IMAP server…")
    src = connect_imap(
        host=src_cfg["host"],
        port=src_cfg.get("port"),
        username=src_cfg["username"],
        password=src_cfg["password"],
        use_ssl=src_cfg.get("ssl", True),
        starttls=src_cfg.get("starttls", False),
        ssl_verify=src_cfg.get("ssl_verify", True),
    )

    src_mailbox = src_cfg.get("mailbox", "INBOX")
    print(f"Selecting source mailbox: {src_mailbox}")
    src.select_folder(src_mailbox, readonly=False)

    print("Listing source messages…")
    query = opts.get("search_query", "ALL")
    search_criteria = query if isinstance(query, list) else [query]
    src_uids: List[int] = src.search(search_criteria)
    print(f"Found {len(src_uids)} messages to consider.")

    dedupe_by = (opts.get("dedupe_by") or "message_id").lower()
    gmail_message_ids: Set[str] = set()
    
    if dedupe_by == "message_id":
        # Note: This can be very slow for large Gmail accounts
        # You might want to make this optional or implement a more efficient approach
        gmail_message_ids = build_gmail_messageid_index(gmail_service, user_id)
        print(f"Indexed {len(gmail_message_ids)} Message-IDs in Gmail.")

    batch_size = int(opts.get("batch_size", 100))
    idle_delay = float(opts.get("idle_delay_sec", 0))
    delete_after_import = bool(opts.get("delete_after_import", False))
    safety_mode = bool(opts.get("safety_mode", True))
    max_retries = int(opts.get("max_retries", 3))
    backoff_sec = float(opts.get("retry_backoff_sec", 2.0))
    gmail_labels = opts.get("gmail_labels", [])
    mark_as_unread = bool(opts.get("mark_as_unread", True))

    fetch_items = [
        b"RFC822",  # Full raw message
        b"FLAGS",
        b"INTERNALDATE",
        b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]",
    ]

    imported = 0
    skipped = 0
    uids_to_delete: List[int] = []

    for batch in chunked(src_uids, batch_size):
        resp = src.fetch(batch, fetch_items)
        
        for uid in batch:
            data = resp.get(uid)
            if not data:
                continue

            raw_msg: bytes = data.get(b"RFC822", b"")
            if not raw_msg:
                continue

            # Extract Message-ID for dedupe + verification
            msgid = extract_message_id(
                data.get(b"BODY[HEADER.FIELDS (MESSAGE-ID)]")
                or data.get(b"BODY[HEADER.FIELDS (MESSAGE-ID)]".lower())
            )

            # Deduplication
            if dedupe_by == "message_id" and msgid and msgid in gmail_message_ids:
                skipped += 1
                continue

            # Import to Gmail
            gmail_msg_id = import_to_gmail_with_retries(
                gmail_service,
                user_id,
                raw_msg,
                gmail_labels,
                mark_as_unread,
                max_retries,
                backoff_sec,
            )

            if not gmail_msg_id:
                # Import failed
                continue

            # Update in-memory index
            if msgid:
                gmail_message_ids.add(msgid)

            imported += 1
            print(f"Imported UID {uid} -> Gmail ID {gmail_msg_id}")

            # Decide whether to delete this UID
            if delete_after_import:
                if safety_mode:
                    verified = verify_on_gmail(gmail_service, user_id, msgid)
                    if verified:
                        uids_to_delete.append(uid)
                    else:
                        print(f"[INFO] Skipping deletion for UID {uid}: verification failed.")
                else:
                    uids_to_delete.append(uid)

            if idle_delay > 0:
                time.sleep(idle_delay)

        print(f"Progress: imported {imported}, skipped {skipped} of {len(src_uids)} total…")

    # Delete verified UIDs from source
    if delete_after_import and uids_to_delete:
        print(f"Deleting {len(uids_to_delete)} source messages…")
        try:
            src.add_flags(uids_to_delete, [b"\\Deleted"])
            src.expunge()
        except Exception as e:
            print(f"[ERROR] Failed to delete/expunge on source: {e}")

    print("\nDone.")
    print(f"Imported: {imported}")
    print(f"Skipped (dedupe): {skipped}")
    if delete_after_import:
        print(f"Deleted from source: {len(uids_to_delete)} (safety_mode={'on' if safety_mode else 'off'})")

    src.logout()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run.py /path/to/config.yaml")
        sys.exit(1)
    
    cfg_path = sys.argv[1]
    cfg = load_config(cfg_path)
    migrate(cfg)
