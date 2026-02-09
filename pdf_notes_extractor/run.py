#!/usr/bin/env python3
"""
PDF Notes Extractor

Downloads PDF files from WebDAV folder, compares current and previous month's
notebooks to find new/modified pages, and emails the extracted pages.

Usage:
    python run.py /path/to/config.yaml
"""

import sys
import os
import hashlib
import shutil
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional, Set
from pathlib import Path
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

try:
    import yaml
except ImportError:
    print("Missing dependency: pyyaml. Install with: pip install pyyaml")
    raise

try:
    from webdav3.client import Client as WebDAVClient
except ImportError:
    print("Missing dependency: webdavclient3. Install with: pip install webdavclient3")
    raise

try:
    import PyPDF2
except ImportError:
    print("Missing dependency: PyPDF2. Install with: pip install PyPDF2")
    raise


def load_config(path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    
    # Defaults
    cfg.setdefault("webdav", {})
    cfg.setdefault("email", {})
    cfg.setdefault("options", {})
    
    o = cfg["options"]
    o.setdefault("temp_dir", "/tmp/pdf_notes_extractor")
    o.setdefault("keep_previous_months", 2)
    o.setdefault("include_current_month", True)
    o.setdefault("include_previous_month", True)
    o.setdefault("compare_method", "md5")
    o.setdefault("attach_extracted_pdf", True)
    
    if "email_body_template" not in o:
        o["email_body_template"] = """Hello,

Attached are the new or modified pages from your PDF notes for {date}.

Total pages extracted: {page_count}
Source files: {source_files}

Best regards,
PDF Notes Extractor"""
    
    return cfg


def get_month_filenames(include_current: bool, include_previous: bool) -> List[Tuple[str, str]]:
    """
    Generate list of PDF filenames to process.
    Returns list of tuples: (filename, description)
    """
    files = []
    now = datetime.now()
    
    if include_current:
        current_month = now.strftime("%Y-%m")
        files.append((f"{current_month}.pdf", current_month))
    
    if include_previous:
        # Get previous month
        first_day_current = now.replace(day=1)
        last_month = first_day_current - timedelta(days=1)
        prev_month = last_month.strftime("%Y-%m")
        files.append((f"{prev_month}.pdf", prev_month))
    
    return files


def setup_webdav_client(config: Dict[str, Any]) -> WebDAVClient:
    """Setup and return WebDAV client."""
    webdav_config = config["webdav"]
    
    options = {
        'webdav_hostname': webdav_config["url"],
        'webdav_login': webdav_config["username"],
        'webdav_password': webdav_config["password"],
    }
    
    client = WebDAVClient(options)
    return client


def download_pdf_from_webdav(
    client: WebDAVClient,
    remote_path: str,
    local_path: str
) -> bool:
    """
    Download a PDF file from WebDAV.
    Returns True if successful, False otherwise.
    """
    try:
        client.download_sync(remote_path=remote_path, local_path=local_path)
        return True
    except Exception as e:
        print(f"Failed to download {remote_path}: {e}")
        return False


def get_pdf_page_hash(pdf_path: str, page_num: int) -> Optional[str]:
    """
    Get MD5 hash of a specific page in a PDF.
    Returns None if page cannot be read.
    """
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            if page_num >= len(reader.pages):
                return None
            
            page = reader.pages[page_num]
            # Extract page content and compute hash
            content = page.extract_text()
            
            # Also include page object data for more accurate comparison
            page_obj = page.get_object()
            page_data = str(page_obj).encode('utf-8')
            
            hash_obj = hashlib.md5()
            hash_obj.update(content.encode('utf-8'))
            hash_obj.update(page_data)
            
            return hash_obj.hexdigest()
    except Exception as e:
        print(f"Error reading page {page_num} from {pdf_path}: {e}")
        return None


def compare_pdfs(old_pdf: str, new_pdf: str, method: str = "md5") -> Set[int]:
    """
    Compare two PDFs and return set of page numbers (0-indexed) that are new or modified.
    
    Args:
        old_pdf: Path to previous version of PDF (can be None if doesn't exist)
        new_pdf: Path to current version of PDF
        method: Comparison method ("md5")
    
    Returns:
        Set of page numbers that are new or modified
    """
    changed_pages = set()
    
    try:
        with open(new_pdf, 'rb') as file:
            new_reader = PyPDF2.PdfReader(file)
            new_page_count = len(new_reader.pages)
            
            # If no old PDF, all pages are new
            if old_pdf is None or not os.path.exists(old_pdf):
                print(f"No previous version found. All {new_page_count} pages considered new.")
                return set(range(new_page_count))
            
            # Read old PDF
            with open(old_pdf, 'rb') as old_file:
                old_reader = PyPDF2.PdfReader(old_file)
                old_page_count = len(old_reader.pages)
                
                print(f"Comparing PDFs: old={old_page_count} pages, new={new_page_count} pages")
                
                # Check each page in new PDF
                for page_num in range(new_page_count):
                    # If page number exceeds old PDF, it's a new page
                    if page_num >= old_page_count:
                        changed_pages.add(page_num)
                        continue
                    
                    # Compare page hashes
                    old_hash = get_pdf_page_hash(old_pdf, page_num)
                    new_hash = get_pdf_page_hash(new_pdf, page_num)
                    
                    if old_hash != new_hash:
                        changed_pages.add(page_num)
                
                print(f"Found {len(changed_pages)} changed/new pages")
                
    except Exception as e:
        print(f"Error comparing PDFs: {e}")
        # On error, consider all pages in new PDF as changed
        try:
            with open(new_pdf, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                return set(range(len(reader.pages)))
        except:
            return set()
    
    return changed_pages


def extract_pages_to_new_pdf(
    source_pdf: str,
    page_numbers: Set[int],
    output_pdf: str
) -> int:
    """
    Extract specific pages from a PDF to a new PDF file.
    Returns number of pages extracted.
    """
    if not page_numbers:
        return 0
    
    try:
        with open(source_pdf, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            writer = PyPDF2.PdfWriter()
            
            # Sort page numbers for sequential extraction
            for page_num in sorted(page_numbers):
                if page_num < len(reader.pages):
                    writer.add_page(reader.pages[page_num])
            
            # Write output PDF
            with open(output_pdf, 'wb') as output_file:
                writer.write(output_file)
            
            return len(page_numbers)
    
    except Exception as e:
        print(f"Error extracting pages: {e}")
        return 0


def send_email_with_attachment(
    config: Dict[str, Any],
    pdf_path: str,
    page_count: int,
    source_files: str,
    date_str: str
):
    """Send email with extracted PDF attached."""
    email_cfg = config["email"]
    options = config["options"]
    
    # Create message
    msg = MIMEMultipart()
    msg['From'] = email_cfg["from_addr"]
    msg['To'] = email_cfg["to_addr"]
    msg['Subject'] = email_cfg["subject"].format(date=date_str)
    
    # Create body
    body = options["email_body_template"].format(
        date=date_str,
        page_count=page_count,
        source_files=source_files
    )
    msg.attach(MIMEText(body, 'plain'))
    
    # Attach PDF if configured
    if options["attach_extracted_pdf"] and os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as file:
            pdf_attachment = MIMEApplication(file.read(), _subtype='pdf')
            pdf_attachment.add_header(
                'Content-Disposition',
                'attachment',
                filename=f'notes_{date_str}.pdf'
            )
            msg.attach(pdf_attachment)
    
    # Send email
    try:
        with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
            server.starttls()
            server.login(email_cfg["username"], email_cfg["password"])
            server.send_message(msg)
        
        print(f"Email sent successfully to {email_cfg['to_addr']}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        raise


def cleanup_old_files(temp_dir: str, keep_months: int):
    """Remove old PDF files from temp directory, keeping only recent months."""
    if not os.path.exists(temp_dir):
        return
    
    try:
        now = datetime.now()
        cutoff_date = now - timedelta(days=keep_months * 31)  # Approximate
        
        for filename in os.listdir(temp_dir):
            if not filename.endswith('.pdf'):
                continue
            
            # Extract date from filename (YYYY-MM.pdf)
            try:
                date_str = filename.replace('.pdf', '')
                file_date = datetime.strptime(date_str, '%Y-%m')
                
                if file_date < cutoff_date:
                    file_path = os.path.join(temp_dir, filename)
                    os.remove(file_path)
                    print(f"Removed old file: {filename}")
            except ValueError:
                # Skip files that don't match expected format
                continue
    
    except Exception as e:
        print(f"Error during cleanup: {e}")


def main(config_path: str = None):
    """Main execution function."""
    if config_path is None:
        if len(sys.argv) < 2:
            config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        else:
            config_path = sys.argv[1]
    
    # Load configuration
    print(f"Loading configuration from {config_path}")
    config = load_config(config_path)
    
    # Setup directories
    temp_dir = config["options"]["temp_dir"]
    os.makedirs(temp_dir, exist_ok=True)
    
    # Setup WebDAV client
    print("Connecting to WebDAV server...")
    webdav_client = setup_webdav_client(config)
    
    # Get files to process
    files_to_process = get_month_filenames(
        config["options"]["include_current_month"],
        config["options"]["include_previous_month"]
    )
    
    if not files_to_process:
        print("No files to process based on configuration")
        return
    
    # Download PDFs from WebDAV
    webdav_folder = config["webdav"].get("folder", "")
    downloaded_files = []
    
    for filename, month_str in files_to_process:
        remote_path = f"{webdav_folder}/{filename}" if webdav_folder else filename
        local_path = os.path.join(temp_dir, f"current_{filename}")
        
        print(f"Downloading {remote_path}...")
        if download_pdf_from_webdav(webdav_client, remote_path, local_path):
            downloaded_files.append((local_path, filename, month_str))
        else:
            print(f"Warning: Could not download {filename}")
    
    if not downloaded_files:
        print("No files were downloaded successfully")
        return
    
    # Process each downloaded file
    all_changed_pages = []
    
    for current_pdf, original_filename, month_str in downloaded_files:
        # Check if we have a previous version
        previous_pdf = os.path.join(temp_dir, original_filename)
        
        # Compare PDFs
        print(f"\nProcessing {original_filename}...")
        changed_pages = compare_pdfs(
            previous_pdf if os.path.exists(previous_pdf) else None,
            current_pdf,
            config["options"]["compare_method"]
        )
        
        if changed_pages:
            all_changed_pages.append((current_pdf, changed_pages, month_str))
        
        # Replace old version with new version
        shutil.move(current_pdf, previous_pdf)
    
    # Extract changed pages to a single PDF
    if all_changed_pages:
        output_pdf = os.path.join(temp_dir, f"extracted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        total_pages = 0
        source_files = []
        
        # Merge all changed pages into one PDF
        writer = PyPDF2.PdfWriter()
        
        for pdf_path, page_nums, month_str in all_changed_pages:
            source_files.append(month_str)
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page_num in sorted(page_nums):
                    if page_num < len(reader.pages):
                        writer.add_page(reader.pages[page_num])
                        total_pages += 1
        
        # Write combined PDF
        with open(output_pdf, 'wb') as output_file:
            writer.write(output_file)
        
        print(f"\nExtracted {total_pages} pages to {output_pdf}")
        
        # Send email
        if total_pages > 0:
            print("Sending email...")
            send_email_with_attachment(
                config,
                output_pdf,
                total_pages,
                ", ".join(source_files),
                datetime.now().strftime("%Y-%m")
            )
            print("Process completed successfully!")
        else:
            print("No pages extracted, skipping email")
    else:
        print("\nNo changes detected in any files")
    
    # Cleanup old files
    print("\nCleaning up old files...")
    cleanup_old_files(temp_dir, config["options"]["keep_previous_months"])


if __name__ == "__main__":
    main()
