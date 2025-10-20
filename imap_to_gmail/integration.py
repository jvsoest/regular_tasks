#!/usr/bin/env python3
"""
Integration example for using imap_to_gmail with the main scheduler.

This shows how to schedule the IMAP to Gmail import as a regular task.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from imap_to_gmail.run import load_config, migrate


def run_imap_to_gmail_import():
    """
    Function to be called by the scheduler.
    
    This can be registered as a job in main.py's scheduler.
    """
    try:
        config_path = os.path.join(
            os.path.dirname(__file__),
            'config.yaml'
        )
        
        print(f"Loading config from: {config_path}")
        cfg = load_config(config_path)
        
        print("Starting IMAP to Gmail import...")
        migrate(cfg)
        
        print("Import completed successfully!")
        return True
        
    except Exception as e:
        print(f"Error during import: {e}")
        import traceback
        traceback.print_exc()
        return False


# Example: How to add this to the main scheduler
"""
In main.py, you can add this job like:

from imap_to_gmail.integration import run_imap_to_gmail_import

# Add to scheduler (example: daily at 2 AM)
scheduler.add_job(
    func=run_imap_to_gmail_import,
    trigger=CronTrigger(hour=2, minute=0),
    id='imap_to_gmail_import',
    name='IMAP to Gmail Import',
    replace_existing=True
)

# Or run on interval (every 6 hours)
scheduler.add_job(
    func=run_imap_to_gmail_import,
    trigger=IntervalTrigger(hours=6),
    id='imap_to_gmail_import',
    name='IMAP to Gmail Import',
    replace_existing=True
)
"""


if __name__ == "__main__":
    """Run standalone for testing."""
    success = run_imap_to_gmail_import()
    sys.exit(0 if success else 1)
