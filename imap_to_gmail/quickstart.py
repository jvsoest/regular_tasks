#!/usr/bin/env python3
"""
Quick Start Script for IMAP to Gmail Import

This script helps you get started with importing emails from IMAP to Gmail.
It checks dependencies, guides OAuth setup, and runs the migration.
"""

import sys
import os
import subprocess

def check_dependencies():
    """Check if required packages are installed."""
    print("Checking dependencies...")
    required = [
        'yaml',
        'imapclient',
        'google.auth',
        'google_auth_oauthlib',
        'googleapiclient'
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package)
            print(f"  ✓ {package}")
        except ImportError:
            print(f"  ✗ {package} (missing)")
            missing.append(package)
    
    if missing:
        print("\nMissing dependencies detected!")
        print("Install with:")
        print("  pip install pyyaml imapclient google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        return False
    
    print("All dependencies are installed!\n")
    return True


def check_credentials():
    """Check if OAuth credentials file exists."""
    creds_file = os.path.join(os.path.dirname(__file__), 'credentials.json')
    template_file = os.path.join(os.path.dirname(__file__), 'credentials.json.template')
    
    print("Checking OAuth credentials...")
    
    if not os.path.exists(creds_file):
        print(f"  ✗ credentials.json not found")
        print("\nYou need to set up Google Cloud OAuth credentials:")
        print("1. Go to: https://console.cloud.google.com/")
        print("2. Create a project or select existing one")
        print("3. Enable Gmail API")
        print("4. Create OAuth 2.0 credentials (Desktop app)")
        print("5. Download credentials.json")
        print(f"6. Place it at: {creds_file}")
        print(f"\nA template is available at: {template_file}")
        return False
    
    print(f"  ✓ credentials.json found")
    return True


def check_config():
    """Check if config file exists and is configured."""
    config_file = os.path.join(os.path.dirname(__file__), 'config.yaml')
    
    print("Checking configuration...")
    
    if not os.path.exists(config_file):
        print(f"  ✗ config.yaml not found at {config_file}")
        return False
    
    # Quick check for placeholder values
    with open(config_file, 'r') as f:
        content = f.read()
        if 'your_password_here' in content or 'YOUR_' in content:
            print(f"  ⚠ config.yaml contains placeholder values")
            print("    Please edit config.yaml with your actual IMAP credentials")
            return False
    
    print(f"  ✓ config.yaml found and appears configured")
    return True


def main():
    """Run the quick start checks and migration."""
    print("=" * 60)
    print("IMAP to Gmail Import - Quick Start")
    print("=" * 60)
    print()
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Check OAuth credentials
    if not check_credentials():
        print("\n❌ Setup incomplete. Please configure OAuth credentials first.")
        sys.exit(1)
    
    # Check config
    if not check_config():
        print("\n❌ Setup incomplete. Please configure config.yaml first.")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✓ All checks passed! Ready to import emails.")
    print("=" * 60)
    print()
    
    # Ask for confirmation
    response = input("Start importing emails? (yes/no): ").strip().lower()
    
    if response in ['yes', 'y']:
        print("\nStarting migration...")
        print("Note: Browser will open for OAuth authentication on first run.\n")
        
        # Import and run
        try:
            from run import load_config, migrate
            
            config_file = os.path.join(os.path.dirname(__file__), 'config.yaml')
            cfg = load_config(config_file)
            migrate(cfg)
            
        except KeyboardInterrupt:
            print("\n\n⚠ Migration interrupted by user.")
            sys.exit(0)
        except Exception as e:
            print(f"\n\n❌ Error during migration: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        print("\nMigration cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
