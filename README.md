# Regular Tasks Scheduler

A Flask-based web application for scheduling and managing recurring tasks. This application provides a user-friendly interface to configure, monitor, and execute various job modules on scheduled intervals.

## Features

- 🔄 **Flexible Scheduling**: Support for interval-based (minutes, hours, days, weeks) and cron-based scheduling
- 🌐 **Web Interface**: Clean, responsive Bootstrap-based UI for job management
- 📦 **Modular Architecture**: Dynamically discovers and loads job modules
- ⚡ **Manual Triggers**: Run jobs immediately via the web interface
- 📊 **Status Monitoring**: Track job execution status, success/failure, and timing
- 💾 **Persistent Configuration**: Jobs are saved to JSON configuration file
- 🐳 **Docker Support**: Containerized deployment ready
- 🔒 **Safety Features**: Built-in retry mechanisms and verification for critical operations

## Available Modules

### Email Move (`email_move`)
IMAP email migration tool with advanced features:
- Copies/moves emails between IMAP mailboxes
- Preserves flags and timestamps
- Deduplication using Message-ID
- Safety mode with verification before deletion
- Marks migrated emails as unread in destination
- Retry mechanisms with exponential backoff

## Quick Start

### Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd regular_tasks
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the application**
   ```bash
   python main.py
   ```

4. **Access the web interface**
   Open your browser and navigate to `http://localhost:8000`

### Docker Deployment

### Using Pre-built Images

The project automatically builds Docker images via GitHub Actions and publishes them to GitHub Container Registry.

1. **Pull the latest image**
   ```bash
   docker pull ghcr.io/OWNER/REPOSITORY:latest
   ```

2. **Run the container**
   ```bash
   docker run -d \
     --name regular-tasks \
     -p 8000:8000 \
     -v $(pwd)/data:/app/data \
     -v $(pwd)/logs:/app/logs \
     ghcr.io/jvsoest/regular_tasks:latest
   ```

### Building Locally

1. **Build the Docker image**
   ```bash
   docker build -t regular-tasks .
   ```

2. **Run the container**
   ```bash
   docker run -d \
     --name regular-tasks \
     -p 8000:8000 \
     -v $(pwd)/data:/app/data \
     -v $(pwd)/logs:/app/logs \
     regular-tasks
   ```

### Docker Compose (Recommended)

Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  regular-tasks:
    image: ghcr.io/OWNER/REPOSITORY:latest  # or build: . for local builds
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./jobs_config.json:/app/jobs_config.json
    environment:
      - FLASK_ENV=production
    restart: unless-stopped
```

Run with:
```bash
docker-compose up -d
```

## Configuration

### Adding a New Job Module

1. **Create a module directory** with a `run.py` file:
   ```
   your_module/
   ├── run.py
   └── config.yaml
   ```

2. **Implement required functions** in `run.py`:
   ```python
   def load_config(path: str):
       # Load configuration from file
       pass
   
   def migrate(cfg):
       # Main execution function
       pass
   
   # OR alternatively:
   def main():
       # Entry point using sys.argv for config file
       pass
   ```

3. **The module will be automatically discovered** by the application

### Email Move Configuration

Create a YAML configuration file for the email_move module:

```yaml
source:
  host: imap.source.com
  port: 993
  username: source@example.com
  password: source_password
  ssl: true
  mailbox: INBOX

dest:
  host: imap.destination.com
  port: 993
  username: dest@example.com
  password: dest_password
  ssl: true
  mailbox: INBOX

options:
  batch_size: 200
  dedupe_by: message_id
  create_dest_mailbox: true
  search_query: ALL
  delete_after_copy: false
  safety_mode: true
  verify_strategy: message_id
  max_retries: 3
  retry_backoff_sec: 2.0
```

## API Endpoints

- `GET /` - Main dashboard
- `GET /add_job` - Add new job form
- `POST /add_job` - Create new job
- `GET /toggle_job/<job_id>` - Enable/disable job
- `GET /run_job/<job_id>` - Manually trigger job
- `GET /remove_job/<job_id>` - Remove job
- `GET /logs/<job_id>` - View job logs
- `GET /api/jobs` - JSON API for job status

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Flask environment | `development` |
| `FLASK_SECRET_KEY` | Secret key for Flask sessions | Auto-generated |
| `SCHEDULER_PORT` | Port to run the application | `8000` |

## File Structure

```
regular_tasks/
├── main.py                 # Main Flask application
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container configuration
├── docker-compose.yml     # Docker Compose setup
├── jobs_config.json       # Job configurations (auto-created)
├── templates/             # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── add_job.html
│   └── logs.html
├── email_move/           # Email migration module
│   ├── run.py
│   └── config.yaml
└── data/                 # Persistent data directory
```

## Troubleshooting

### Common Issues

1. **Module Import Errors**
   - Ensure your module has a `run.py` file
   - Check that required functions (`main` or `migrate`) are implemented

2. **Permission Errors in Docker**
   - Ensure proper volume mounting
   - Check file permissions on mounted directories

3. **Job Execution Failures**
   - Check job logs in the web interface
   - Verify configuration file syntax
   - Ensure all required dependencies are installed

### Logs

- Application logs are printed to console
- Individual job execution logs are stored in job registry
- Access logs via the web interface: `/logs/<job_id>`

## Development

### Adding New Features

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

### Module Development Guidelines

- Implement either `main()` or `migrate(cfg)` function
- Use `load_config(path)` for configuration loading
- Handle errors gracefully
- Provide informative logging
- Follow Python best practices

## Security Considerations

- Change the default Flask secret key in production
- Use environment variables for sensitive configuration
- Implement proper authentication if exposing to internet
- Regularly update dependencies
- Use HTTPS in production environments

## License

This project is open source. Please check the LICENSE file for details.

## Contributing

Contributions are welcome! Please read the development guidelines and submit pull requests for any improvements.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review existing issues in the repository
3. Create a new issue with detailed information about the problem
