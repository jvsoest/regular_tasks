# IMAP to Gmail Import Module

## 📋 Overview

This module provides a robust solution for importing emails from any IMAP server into Gmail using the Gmail API. Unlike traditional IMAP-to-IMAP migration, this approach leverages Gmail's `messages.import` endpoint for better performance and metadata preservation.

## ✨ Key Features

- **IMAP Source**: Read from any IMAP server (not just Gmail)
- **Gmail API Destination**: Uses Gmail API for efficient, reliable imports
- **Metadata Preservation**: Maintains original timestamps, headers, and thread information
- **OAuth2 Security**: Secure authentication with Google (no password storage)
- **Smart Deduplication**: Avoids importing duplicate emails based on Message-ID
- **Safe Move Operations**: Optional deletion from source with verification
- **Retry Logic**: Automatic retry with exponential backoff for reliability
- **Gmail Labels**: Apply custom labels to imported messages
- **Read/Unread Control**: Choose whether to mark messages as read or unread
- **Batch Processing**: Efficient processing of large mailboxes

## 📁 Module Structure

```
imap_to_gmail/
├── __init__.py                  # Module initialization
├── run.py                       # Main import script
├── config.yaml                  # Your configuration (create from template)
├── config.yaml.template         # Configuration template with examples
├── credentials.json             # OAuth2 credentials (download from Google)
├── credentials.json.template    # Credentials template/guide
├── token.json                   # OAuth2 token (auto-generated on first run)
├── quickstart.py                # Interactive setup and run script
├── integration.py               # Integration example for main.py scheduler
└── README.md                    # Detailed documentation
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Or specifically for this module:

```bash
pip install pyyaml imapclient google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

### 2. Set Up Google Cloud OAuth

1. Visit [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project or select existing
3. Enable **Gmail API**:
   - APIs & Services → Library → Search "Gmail API" → Enable
4. Create **OAuth 2.0 Credentials**:
   - APIs & Services → Credentials → Create Credentials
   - Choose "OAuth client ID" → "Desktop app"
   - Download the JSON file
5. Save as `imap_to_gmail/credentials.json`

### 3. Configure IMAP Source

Copy and edit the configuration:

```bash
cd imap_to_gmail
cp config.yaml.template config.yaml
nano config.yaml  # Edit with your IMAP server details
```

### 4. Run the Import

**Option A: Interactive Quick Start** (Recommended for first time)

```bash
cd imap_to_gmail
python quickstart.py
```

This will:
- Check all dependencies
- Verify OAuth credentials are set up
- Validate configuration
- Guide you through first-time OAuth authentication
- Run the import

**Option B: Direct Script**

```bash
cd imap_to_gmail
python run.py config.yaml
```

**Option C: As a Module**

```python
from imap_to_gmail.run import load_config, migrate

config = load_config('imap_to_gmail/config.yaml')
migrate(config)
```

## 🔧 Configuration

### Basic Configuration

```yaml
source:
  host: imap.example.com
  port: 993
  username: you@example.com
  password: your_password
  ssl: true
  mailbox: INBOX

gmail:
  credentials_file: credentials.json
  token_file: token.json
  user_id: me

options:
  search_query: ALL
  batch_size: 100
  dedupe_by: message_id
  delete_after_import: false
  safety_mode: true
  gmail_labels: []
  mark_as_unread: true
```

### Common Use Cases

**Import only unread messages:**
```yaml
options:
  search_query: UNSEEN
  delete_after_import: false
```

**Move all messages (full migration):**
```yaml
options:
  search_query: ALL
  delete_after_import: true
  safety_mode: true
```

**Import messages from specific date:**
```yaml
options:
  search_query: ["SINCE", "01-Jan-2024"]
```

**Apply labels to imported messages:**
```yaml
options:
  gmail_labels: ['Archive', 'Migration', 'Old-Account']
```

## 🔐 Security

- **OAuth2**: More secure than password-based IMAP
- **Token Storage**: `token.json` stores your access token (keep private!)
- **Credentials**: `credentials.json` contains OAuth client ID (less sensitive)
- **Git Ignore**: Both files are automatically excluded from version control

⚠️ **Important**: Never commit `credentials.json` or `token.json` to public repositories!

## 🔄 Integration with Main Scheduler

To run imports on a schedule, integrate with `main.py`:

```python
from imap_to_gmail.integration import run_imap_to_gmail_import
from apscheduler.triggers.cron import CronTrigger

# Daily at 2 AM
scheduler.add_job(
    func=run_imap_to_gmail_import,
    trigger=CronTrigger(hour=2, minute=0),
    id='imap_to_gmail',
    name='IMAP to Gmail Import'
)
```

See `integration.py` for more examples.

## 🆚 Why Gmail API vs IMAP?

### Traditional Approach (IMAP → IMAP)
- ❌ Slower performance
- ❌ Limited metadata preservation
- ❌ Size limitations
- ❌ Less reliable for automation
- ✅ Works with any IMAP server

### This Module (IMAP → Gmail API)
- ✅ Optimized for Gmail
- ✅ Better metadata preservation
- ✅ No practical size limits
- ✅ More reliable
- ✅ Native label support
- ✅ OAuth2 security
- ❌ Gmail-specific (destination only)

## 📊 Performance

- **Batch Processing**: Configurable batch size (default: 100 messages)
- **Deduplication**: Optional in-memory index for Message-IDs
- **Rate Limiting**: Built-in retry with exponential backoff
- **Large Mailboxes**: Tested with 10,000+ messages

**Note**: Initial deduplication index building can be slow for very large Gmail accounts (50,000+ messages). Consider running without deduplication for first import, then enable it for incremental imports.

## 🐛 Troubleshooting

### Authentication Issues

**"Missing credentials.json"**
- Download OAuth credentials from Google Cloud Console
- Place in `imap_to_gmail/` directory

**"Invalid grant" or token errors**
- Delete `token.json`
- Re-run the script to re-authenticate

### Import Failures

**"Quota exceeded"**
- Check Gmail API quota in Google Cloud Console
- Add delays: `idle_delay_sec: 1`
- Reduce batch size: `batch_size: 50`

**"Message too large"**
- Gmail has a 25 MB limit per message
- Large messages will be skipped automatically

### Slow Performance

**Deduplication is slow**
- Building Gmail Message-ID index can take time
- Options:
  - Set `dedupe_by: none` (if no duplicates expected)
  - Use smaller `batch_size`
  - Run initial import without deduplication

**IMAP connection timeouts**
- Add delays: `idle_delay_sec: 0.5`
- Reduce batch size: `batch_size: 50`
- Check network connectivity

## 📝 Logging

The module outputs detailed progress information:
- Connection status
- Message counts
- Import progress
- Errors and retries
- Deletion confirmations (if move mode)

When integrated with `main.py`, logs are automatically captured to the log directory.

## 🔒 Best Practices

1. **Test First**: Run with `delete_after_import: false` first
2. **Use Safety Mode**: Keep `safety_mode: true` when moving emails
3. **Start Small**: Test with a small search query first
4. **Backup**: Have backups before running delete operations
5. **Monitor Quota**: Check Google Cloud Console for API usage
6. **Secure Tokens**: Keep `token.json` private and secure

## 🤝 Comparison with `email_move` Module

### `email_move` (IMAP → IMAP)
- Both source and destination use IMAP
- Works with any IMAP server (destination)
- Good for non-Gmail destinations
- Uses IMAP APPEND for copying

### `imap_to_gmail` (IMAP → Gmail API)
- Source uses IMAP, destination uses Gmail API
- Gmail-specific destination
- Better performance for Gmail
- Uses Gmail's messages.import endpoint
- OAuth2 security

**Use `imap_to_gmail` when**: Migrating to Gmail or Google Workspace
**Use `email_move` when**: Migrating between non-Gmail IMAP servers

## 📚 Additional Resources

- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [OAuth2 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2/native-app)
- [IMAP Search Syntax](https://www.rfc-editor.org/rfc/rfc3501#section-6.4.4)
- [Gmail API Python Quickstart](https://developers.google.com/gmail/api/quickstart/python)

## 📄 License

Same as parent project.

## 👤 Author

Part of the `regular_tasks` project by jvsoest.
