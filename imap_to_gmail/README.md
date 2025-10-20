# IMAP to Gmail API Import

This module reads emails from any IMAP server and imports them into Gmail using the Gmail API's `messages.import` endpoint. This approach is more efficient and preserves email metadata better than using IMAP for both source and destination.

## Features

- ✅ Read emails from any IMAP server (source)
- ✅ Import to Gmail using Gmail API (preserves metadata)
- ✅ OAuth2 authentication for Gmail
- ✅ Deduplication by Message-ID
- ✅ Optional move behavior (delete from source after import)
- ✅ Safety mode with verification before deletion
- ✅ Retry logic with exponential backoff
- ✅ Apply Gmail labels to imported messages
- ✅ Control read/unread status
- ✅ Preserve original internal date

## Prerequisites

### 1. Install Dependencies

```bash
pip install pyyaml imapclient google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

### 2. Set Up Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Gmail API:
   - Go to "APIs & Services" > "Library"
   - Search for "Gmail API"
   - Click "Enable"
4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app" as application type
   - Download the credentials JSON file
   - Save it as `credentials.json` in the module directory

### 3. Configure IMAP Source

Update `config.yaml` with your IMAP server details:
- Host, port, username, password
- Source mailbox (default: INBOX)

## Configuration

Edit `config.yaml`:

```yaml
source:
  host: imap.example.com
  port: 993
  username: your_email@example.com
  password: your_password
  ssl: true
  mailbox: INBOX

gmail:
  credentials_file: credentials.json  # OAuth2 credentials from Google Cloud
  token_file: token.json             # Token will be saved here after first auth
  user_id: me                        # 'me' for authenticated user

options:
  search_query: ALL              # IMAP search query
  batch_size: 100                # Messages per batch
  dedupe_by: message_id         # Avoid duplicates
  idle_delay_sec: 0             # Delay between messages
  
  delete_after_import: false    # Move mode (delete from source)
  safety_mode: true             # Verify before deleting
  max_retries: 3
  retry_backoff_sec: 2.0
  
  gmail_labels: []              # Labels to apply (e.g., ['Important', 'Migration'])
  mark_as_unread: true         # Import as unread
```

## Usage

### First Run (OAuth Authentication)

On the first run, a browser window will open for OAuth authentication:

```bash
python run.py config.yaml
```

1. Sign in with your Google account
2. Grant the requested permissions
3. The token will be saved to `token.json` for future use

### Subsequent Runs

```bash
python run.py config.yaml
```

The saved token will be used automatically.

## How It Works

1. **Connect to IMAP**: Connects to source IMAP server
2. **Authenticate with Gmail API**: Uses OAuth2 for secure access
3. **List Messages**: Retrieves message UIDs from source mailbox
4. **Deduplication** (optional): Builds index of Message-IDs in Gmail to avoid duplicates
5. **Import Loop**:
   - Fetch raw message from IMAP (RFC822 format)
   - Import to Gmail using `messages.import` API
   - Apply labels and read/unread status
   - Optionally verify and delete from source
6. **Cleanup**: Expunge deleted messages from source (if move mode)

## Gmail API vs IMAP for Gmail

### Why use Gmail API instead of IMAP for destination?

1. **Better Performance**: Gmail API is optimized for Gmail operations
2. **Preserved Metadata**: The `messages.import` endpoint preserves:
   - Internal date (message timestamp)
   - Original headers
   - Thread information
3. **No Size Limitations**: Better handling of large messages
4. **Label Support**: Native Gmail label operations
5. **Reliability**: More robust than IMAP for programmatic access
6. **OAuth2 Security**: More secure than IMAP password authentication

## Advanced Options

### Custom Search Query

Search for specific messages on source:

```yaml
options:
  search_query: ["UNSEEN", "SINCE", "01-Jan-2024"]  # Unread messages since Jan 1, 2024
```

### Apply Gmail Labels

```yaml
options:
  gmail_labels: ['Migration', 'Archive']  # Apply these labels to imported messages
```

### Move Mode with Safety

```yaml
options:
  delete_after_import: true   # Delete from source after successful import
  safety_mode: true           # Verify message exists in Gmail before deletion
```

## Security Notes

- **credentials.json**: Contains your OAuth2 client credentials (not sensitive alone)
- **token.json**: Contains your access token (keep secure!)
- Add both to `.gitignore` if using version control
- Never commit these files to public repositories

## Troubleshooting

### "Missing credentials.json"
Download OAuth2 credentials from Google Cloud Console as described in Prerequisites.

### "Invalid grant" or token errors
Delete `token.json` and re-authenticate.

### Slow deduplication
Building the Gmail Message-ID index can be slow for large mailboxes. Consider:
- Setting `dedupe_by: none` if you're sure there are no duplicates
- Using a smaller batch size
- Running initial import without deduplication, then enable it for subsequent runs

### Import failures
Check:
- Gmail API quota limits (check Google Cloud Console)
- Message size (Gmail has limits)
- Network connectivity

## Integration with Main Application

To integrate with the main task scheduler (`main.py`), you can call this module's `migrate()` function:

```python
from imap_to_gmail.run import load_config, migrate

config = load_config('imap_to_gmail/config.yaml')
migrate(config)
```

## License

Same as parent project.
