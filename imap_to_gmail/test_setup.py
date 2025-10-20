#!/usr/bin/env python3
"""
Test Script for IMAP to Gmail Import

This script tests the configuration and connections without performing
any actual import operations. Use this to verify everything is set up correctly.
"""

import sys
import os
import ssl
from typing import Optional

def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")
    tests = {
        'yaml': 'pyyaml',
        'imapclient': 'imapclient',
        'google.auth': 'google-auth',
        'google_auth_oauthlib': 'google-auth-oauthlib',
        'googleapiclient': 'google-api-python-client'
    }
    
    failed = []
    for module, package in tests.items():
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except ImportError:
            print(f"  ✗ {module} (install with: pip install {package})")
            failed.append(package)
    
    if failed:
        print(f"\n❌ Missing packages. Install with:")
        print(f"  pip install {' '.join(failed)}")
        return False
    
    print("✓ All required modules available\n")
    return True


def test_config_file():
    """Test that config file exists and is valid YAML."""
    print("Testing configuration file...")
    import yaml
    
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    
    if not os.path.exists(config_path):
        print(f"  ✗ config.yaml not found")
        print(f"    Expected at: {config_path}")
        print(f"    Copy config.yaml.template to config.yaml and edit it")
        return False, None
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        print(f"  ✓ config.yaml found and valid")
        
        # Check for required sections
        required = ['source', 'gmail', 'options']
        for section in required:
            if section not in config:
                print(f"  ✗ Missing section: {section}")
                return False, None
            print(f"  ✓ Section '{section}' present")
        
        # Check for placeholder values
        warnings = []
        config_str = str(config)
        if 'your_password_here' in config_str:
            warnings.append("Password placeholders found in config")
        if 'YOUR_' in config_str:
            warnings.append("Placeholder values found in config")
        
        if warnings:
            print("  ⚠ Warnings:")
            for warning in warnings:
                print(f"    - {warning}")
        
        print()
        return True, config
        
    except yaml.YAMLError as e:
        print(f"  ✗ Invalid YAML: {e}")
        return False, None
    except Exception as e:
        print(f"  ✗ Error reading config: {e}")
        return False, None


def test_credentials_file():
    """Test that OAuth credentials file exists."""
    print("Testing OAuth credentials...")
    
    creds_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
    
    if not os.path.exists(creds_path):
        print(f"  ✗ credentials.json not found")
        print(f"    Expected at: {creds_path}")
        print(f"    Download from Google Cloud Console")
        return False
    
    try:
        import json
        with open(creds_path, 'r') as f:
            creds = json.load(f)
        
        if 'installed' in creds or 'web' in creds:
            print(f"  ✓ credentials.json found and appears valid")
            
            # Check for placeholders
            creds_str = str(creds)
            if 'YOUR_' in creds_str or 'your-' in creds_str:
                print(f"  ⚠ Credentials file may contain placeholders")
                print(f"    Replace with actual credentials from Google Cloud Console")
                return False
            
            print()
            return True
        else:
            print(f"  ✗ credentials.json doesn't have expected structure")
            return False
            
    except json.JSONDecodeError as e:
        print(f"  ✗ Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"  ✗ Error reading credentials: {e}")
        return False


def test_imap_connection(config: dict) -> bool:
    """Test connection to IMAP server."""
    print("Testing IMAP connection...")
    
    try:
        from imapclient import IMAPClient
        
        src = config['source']
        host = src['host']
        port = src.get('port', 993)
        username = src['username']
        password = src['password']
        use_ssl = src.get('ssl', True)
        
        print(f"  Connecting to {host}:{port} as {username}...")
        
        ssl_context = None
        if use_ssl:
            ssl_context = ssl.create_default_context()
            if not src.get('ssl_verify', True):
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
        
        if use_ssl:
            client = IMAPClient(host, port=port, ssl=True, ssl_context=ssl_context)
        else:
            client = IMAPClient(host, port=port, ssl=False)
        
        print(f"  Logging in...")
        client.login(username, password)
        
        print(f"  Selecting mailbox...")
        mailbox = src.get('mailbox', 'INBOX')
        client.select_folder(mailbox, readonly=True)
        
        # Get message count
        messages = client.search(['ALL'])
        print(f"  ✓ Connected successfully!")
        print(f"  ✓ Found {len(messages)} messages in {mailbox}")
        
        client.logout()
        print()
        return True
        
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        print(f"    Check your IMAP credentials and network connection")
        print()
        return False


def test_gmail_auth(config: dict) -> bool:
    """Test Gmail API authentication."""
    print("Testing Gmail API authentication...")
    
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        
        gmail_cfg = config['gmail']
        credentials_file = gmail_cfg.get('credentials_file', 'credentials.json')
        token_file = gmail_cfg.get('token_file', 'token.json')
        
        credentials_path = os.path.join(os.path.dirname(__file__), credentials_file)
        token_path = os.path.join(os.path.dirname(__file__), token_file)
        
        SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
        
        creds = None
        
        # Check for existing token
        if os.path.exists(token_path):
            print(f"  Found existing token file")
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print(f"  Refreshing expired token...")
                creds.refresh(Request())
            else:
                print(f"  No valid token found. Starting OAuth flow...")
                print(f"  (Browser will open for authentication)")
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save the credentials
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
            print(f"  ✓ Token saved to {token_file}")
        else:
            print(f"  ✓ Valid token found")
        
        # Test Gmail API access
        print(f"  Testing Gmail API access...")
        service = build('gmail', 'v1', credentials=creds)
        
        # Get user profile
        profile = service.users().getProfile(userId='me').execute()
        email = profile.get('emailAddress', 'unknown')
        
        print(f"  ✓ Successfully authenticated!")
        print(f"  ✓ Connected to: {email}")
        print()
        return True
        
    except Exception as e:
        print(f"  ✗ Authentication failed: {e}")
        print(f"    Check your credentials.json file")
        print()
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("IMAP to Gmail Import - Configuration Test")
    print("=" * 70)
    print()
    
    results = {}
    
    # Test imports
    results['imports'] = test_imports()
    
    if not results['imports']:
        print("\n❌ Cannot proceed without required packages.")
        print("Install dependencies first:")
        print("  pip install pyyaml imapclient google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        sys.exit(1)
    
    # Test config
    results['config'], config = test_config_file()
    
    # Test credentials
    results['credentials'] = test_credentials_file()
    
    # Test connections if config is valid
    if results['config'] and config:
        results['imap'] = test_imap_connection(config)
        
        if results['credentials']:
            results['gmail'] = test_gmail_auth(config)
        else:
            results['gmail'] = False
    else:
        results['imap'] = False
        results['gmail'] = False
    
    # Summary
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {test_name.title()}")
        if not passed:
            all_passed = False
    
    print()
    
    if all_passed:
        print("✓ All tests passed! You're ready to import emails.")
        print("\nRun the import with:")
        print("  python run.py config.yaml")
        print("or")
        print("  python quickstart.py")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please fix the issues above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
