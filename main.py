import os
import sys
import importlib
import json
import traceback
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import atexit
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'  # Change this in production

# Global scheduler
scheduler = BackgroundScheduler()
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# Job registry to store job configurations
JOBS_CONFIG_FILE = 'jobs_config.json'
LOG_DIRECTORY = 'log'

# Log rotation configuration from environment variables
LOG_ROTATION_DAYS = int(os.getenv('LOG_ROTATION_DAYS', '7'))  # Keep logs for 7 days by default
LOG_ROTATION_COUNT = int(os.getenv('LOG_ROTATION_COUNT', '10'))  # Keep max 10 files per job by default
LOG_ROTATION_ENABLED = os.getenv('LOG_ROTATION_ENABLED', 'true').lower() == 'true'

jobs_registry: Dict[str, Dict[str, Any]] = {}

class LogManager:
    @staticmethod
    def ensure_log_directory():
        """Ensure log directory exists."""
        os.makedirs(LOG_DIRECTORY, exist_ok=True)
    
    @staticmethod
    def get_log_file_path(job_id: str, timestamp: str = None) -> str:
        """Get the path for a job's log file."""
        LogManager.ensure_log_directory()
        if timestamp is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return os.path.join(LOG_DIRECTORY, f"{job_id}_{timestamp}.log")
    
    @staticmethod
    def get_latest_log_file(job_id: str) -> Optional[str]:
        """Get the path to the most recent log file for a job."""
        LogManager.ensure_log_directory()
        log_files = [f for f in os.listdir(LOG_DIRECTORY) 
                    if f.startswith(f"{job_id}_") and f.endswith('.log')]
        if log_files:
            log_files.sort(reverse=True)  # Most recent first
            return os.path.join(LOG_DIRECTORY, log_files[0])
        return None
    
    @staticmethod
    def get_log_files_for_job(job_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get a list of log files for a specific job."""
        LogManager.ensure_log_directory()
        log_files = [f for f in os.listdir(LOG_DIRECTORY) 
                    if f.startswith(f"{job_id}_") and f.endswith('.log')]
        log_files.sort(reverse=True)  # Most recent first
        
        result = []
        for log_file in log_files[:limit]:
            file_path = os.path.join(LOG_DIRECTORY, log_file)
            try:
                stat_info = os.stat(file_path)
                # Extract timestamp from filename
                timestamp_str = log_file.replace(f"{job_id}_", "").replace(".log", "")
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                except ValueError:
                    timestamp = datetime.fromtimestamp(stat_info.st_mtime)
                
                result.append({
                    'filename': log_file,
                    'path': file_path,
                    'size': stat_info.st_size,
                    'timestamp': timestamp,
                    'timestamp_str': timestamp.strftime('%Y-%m-%d %H:%M:%S')
                })
            except OSError:
                continue
        
        return result
    
    @staticmethod
    def read_log_file(file_path: str, max_lines: int = 1000) -> str:
        """Read a log file with optional line limit."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > max_lines:
                    lines = lines[-max_lines:]  # Get last N lines
                return ''.join(lines)
        except Exception as e:
            return f"Error reading log file: {e}"
    
    @staticmethod
    def cleanup_old_logs(job_id: str = None, keep_count: int = 5):
        """Clean up old log files, keeping only the most recent ones."""
        LogManager.ensure_log_directory()
        
        if job_id:
            # Clean logs for specific job
            log_files = [f for f in os.listdir(LOG_DIRECTORY) 
                        if f.startswith(f"{job_id}_") and f.endswith('.log')]
        else:
            # Clean all log files
            log_files = [f for f in os.listdir(LOG_DIRECTORY) if f.endswith('.log')]
        
        log_files.sort(reverse=True)  # Most recent first
        
        # Remove old files
        for log_file in log_files[keep_count:]:
            try:
                os.remove(os.path.join(LOG_DIRECTORY, log_file))
            except OSError:
                pass

    @staticmethod
    def rotate_logs_by_age(max_days: int = None):
        """Remove log files older than specified days."""
        if max_days is None:
            max_days = LOG_ROTATION_DAYS
            
        if max_days <= 0:
            return  # Rotation disabled
            
        LogManager.ensure_log_directory()
        
        cutoff_time = datetime.now().timestamp() - (max_days * 24 * 60 * 60)
        removed_count = 0
        
        try:
            for filename in os.listdir(LOG_DIRECTORY):
                if not filename.endswith('.log'):
                    continue
                    
                file_path = os.path.join(LOG_DIRECTORY, filename)
                try:
                    if os.path.getmtime(file_path) < cutoff_time:
                        os.remove(file_path)
                        removed_count += 1
                except OSError:
                    continue
                    
        except OSError:
            pass
            
        return removed_count

    @staticmethod
    def rotate_logs_by_count(job_id: str = None, max_count: int = None):
        """Keep only the most recent N log files per job."""
        if max_count is None:
            max_count = LOG_ROTATION_COUNT
            
        if max_count <= 0:
            return  # Rotation disabled
            
        LogManager.ensure_log_directory()
        removed_count = 0
        
        if job_id:
            # Rotate logs for specific job
            jobs_to_rotate = [job_id]
        else:
            # Find all unique job IDs from log files
            jobs_to_rotate = set()
            try:
                for filename in os.listdir(LOG_DIRECTORY):
                    if filename.endswith('.log') and '_' in filename:
                        job_part = filename.split('_')[0]
                        if job_part:
                            jobs_to_rotate.add(job_part)
            except OSError:
                return 0
                
        for job in jobs_to_rotate:
            try:
                job_logs = []
                for filename in os.listdir(LOG_DIRECTORY):
                    if filename.startswith(f"{job}_") and filename.endswith('.log'):
                        file_path = os.path.join(LOG_DIRECTORY, filename)
                        try:
                            mtime = os.path.getmtime(file_path)
                            job_logs.append((filename, file_path, mtime))
                        except OSError:
                            continue
                
                # Sort by modification time (newest first)
                job_logs.sort(key=lambda x: x[2], reverse=True)
                
                # Remove files beyond max_count
                for filename, file_path, _ in job_logs[max_count:]:
                    try:
                        os.remove(file_path)
                        removed_count += 1
                    except OSError:
                        continue
                        
            except OSError:
                continue
                
        return removed_count

    @staticmethod
    def perform_log_rotation(job_id: str = None):
        """Perform complete log rotation based on configuration."""
        if not LOG_ROTATION_ENABLED:
            return {'age_removed': 0, 'count_removed': 0}
            
        results = {}
        
        # Age-based rotation (applies to all logs)
        age_removed = LogManager.rotate_logs_by_age(LOG_ROTATION_DAYS)
        results['age_removed'] = age_removed
        
        # Count-based rotation (per job or all jobs)
        count_removed = LogManager.rotate_logs_by_count(job_id, LOG_ROTATION_COUNT)
        results['count_removed'] = count_removed
        
        return results

    @staticmethod
    def get_rotation_info():
        """Get current rotation configuration and statistics."""
        LogManager.ensure_log_directory()
        
        # Count total log files
        total_files = 0
        total_size = 0
        oldest_file = None
        newest_file = None
        
        try:
            for filename in os.listdir(LOG_DIRECTORY):
                if filename.endswith('.log'):
                    file_path = os.path.join(LOG_DIRECTORY, filename)
                    try:
                        stat_info = os.stat(file_path)
                        total_files += 1
                        total_size += stat_info.st_size
                        
                        mtime = stat_info.st_mtime
                        if oldest_file is None or mtime < oldest_file[1]:
                            oldest_file = (filename, mtime)
                        if newest_file is None or mtime > newest_file[1]:
                            newest_file = (filename, mtime)
                    except OSError:
                        continue
        except OSError:
            pass
            
        return {
            'enabled': LOG_ROTATION_ENABLED,
            'rotation_days': LOG_ROTATION_DAYS,
            'rotation_count': LOG_ROTATION_COUNT,
            'total_files': total_files,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'oldest_file': {
                'name': oldest_file[0] if oldest_file else None,
                'age_days': round((datetime.now().timestamp() - oldest_file[1]) / (24 * 60 * 60), 1) if oldest_file else None
            } if oldest_file else None,
            'newest_file': {
                'name': newest_file[0] if newest_file else None,
                'age_days': round((datetime.now().timestamp() - newest_file[1]) / (24 * 60 * 60), 1) if newest_file else None
            } if newest_file else None
        }

class JobManager:
    def __init__(self):
        self.available_modules = self._discover_modules()
        self.load_jobs_config()
    
    def _discover_modules(self) -> List[str]:
        """Discover available job modules in the current directory."""
        modules = []
        for item in os.listdir('.'):
            if os.path.isdir(item) and not item.startswith('.') and not item.startswith('__'):
                # Check if module has a run.py file
                if os.path.exists(os.path.join(item, 'run.py')):
                    modules.append(item)
        return modules
    
    def load_jobs_config(self):
        """Load job configurations from file."""
        global jobs_registry
        if os.path.exists(JOBS_CONFIG_FILE):
            try:
                with open(JOBS_CONFIG_FILE, 'r') as f:
                    jobs_registry = json.load(f)
            except Exception as e:
                print(f"Error loading jobs config: {e}")
                jobs_registry = {}
        
        # Restore scheduled jobs
        for job_id, config in jobs_registry.items():
            if config.get('enabled', False):
                self._schedule_job(job_id, config)
    
    def save_jobs_config(self):
        """Save job configurations to file."""
        try:
            with open(JOBS_CONFIG_FILE, 'w') as f:
                json.dump(jobs_registry, f, indent=2)
        except Exception as e:
            print(f"Error saving jobs config: {e}")
    
    def _schedule_job(self, job_id: str, config: Dict[str, Any]):
        """Schedule a job with the scheduler."""
        try:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            
            interval_type = config.get('interval_type', 'minutes')
            interval_value = config.get('interval_value', 60)
            
            if interval_type == 'cron':
                # For cron expressions
                cron_expr = config.get('cron_expression', '0 * * * *')
                trigger = CronTrigger.from_crontab(cron_expr)
            else:
                # For interval-based scheduling
                trigger = IntervalTrigger(
                    **{interval_type: interval_value}
                )
            
            scheduler.add_job(
                func=self._execute_job,
                trigger=trigger,
                id=job_id,
                args=[job_id],
                replace_existing=True
            )
            print(f"Scheduled job {job_id}")
        except Exception as e:
            print(f"Error scheduling job {job_id}: {e}")
    
    def _execute_job(self, job_id: str):
        """Execute a job module with persistent logging."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file_path = LogManager.get_log_file_path(job_id, timestamp)
        
        # Create a logger for this job execution
        job_logger = logging.getLogger(f"job_{job_id}_{timestamp}")
        job_logger.setLevel(logging.INFO)
        
        # Remove any existing handlers
        for handler in job_logger.handlers[:]:
            job_logger.removeHandler(handler)
        
        # Create file handler
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        job_logger.addHandler(file_handler)
        
        try:
            config = jobs_registry.get(job_id)
            if not config:
                error_msg = f"Job {job_id} not found in registry"
                job_logger.error(error_msg)
                print(error_msg)
                return
            
            module_name = config['module']
            config_file = config.get('config_file')
            
            job_logger.info(f"Starting job execution: {job_id}")
            job_logger.info(f"Module: {module_name}")
            job_logger.info(f"Config file: {config_file}")
            
            # Update last run time
            jobs_registry[job_id]['last_run'] = datetime.now().isoformat()
            jobs_registry[job_id]['status'] = 'running'
            jobs_registry[job_id]['last_log_file'] = log_file_path
            self.save_jobs_config()
            
            # Add the module directory to Python path temporarily
            module_path = os.path.abspath(module_name)
            if module_path not in sys.path:
                sys.path.insert(0, module_path)
                job_logger.info(f"Added module path: {module_path}")
            
            try:
                # Import and run the module
                run_module_path = f"{module_name}.run"
                if run_module_path in sys.modules:
                    importlib.reload(sys.modules[run_module_path])
                    job_logger.info(f"Reloaded module: {run_module_path}")
                
                module = importlib.import_module(run_module_path)
                job_logger.info(f"Imported module: {run_module_path}")
                
                # Capture stdout and stderr during execution
                stdout_capture = StringIO()
                stderr_capture = StringIO()
                
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    # Try different execution strategies based on module structure
                    if hasattr(module, 'main') and config_file:
                        job_logger.info("Executing module.main() with config file")
                        # Execute with config file as command line argument
                        original_argv = sys.argv
                        sys.argv = ['run.py', config_file]
                        try:
                            module.main()
                        finally:
                            sys.argv = original_argv
                            
                    elif hasattr(module, 'migrate') and config_file:
                        job_logger.info("Executing module.migrate() with config")
                        # For email_move type modules, load config directly
                        if hasattr(module, 'load_config'):
                            cfg = module.load_config(config_file)
                            module.migrate(cfg)
                        else:
                            # Try to import yaml and load config manually
                            import yaml
                            with open(config_file, 'r') as f:
                                cfg = yaml.safe_load(f)
                            module.migrate(cfg)
                            
                    else:
                        error_msg = f"Module {module_name} doesn't have expected entry points (main or migrate)"
                        job_logger.error(error_msg)
                        print(error_msg)
                        return
                
                # Log captured output
                stdout_content = stdout_capture.getvalue()
                stderr_content = stderr_capture.getvalue()
                
                if stdout_content:
                    job_logger.info("STDOUT OUTPUT:")
                    for line in stdout_content.strip().split('\n'):
                        if line.strip():
                            job_logger.info(f"  {line}")
                
                if stderr_content:
                    job_logger.warning("STDERR OUTPUT:")
                    for line in stderr_content.strip().split('\n'):
                        if line.strip():
                            job_logger.warning(f"  {line}")
                    
            finally:
                # Remove module path from sys.path
                if module_path in sys.path:
                    sys.path.remove(module_path)
                    job_logger.info(f"Removed module path: {module_path}")
            
            # Update success status
            jobs_registry[job_id]['status'] = 'success'
            jobs_registry[job_id]['last_success'] = datetime.now().isoformat()
            job_logger.info("Job completed successfully")
            
        except Exception as e:
            error_msg = f"Error executing job {job_id}: {e}"
            job_logger.error(error_msg)
            job_logger.error("Exception traceback:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    job_logger.error(f"  {line}")
            
            print(error_msg)
            traceback.print_exc()
            jobs_registry[job_id]['status'] = 'error'
            jobs_registry[job_id]['last_error'] = str(e)
        finally:
            # Clean up logger handlers
            for handler in job_logger.handlers[:]:
                handler.close()
                job_logger.removeHandler(handler)
            
            self.save_jobs_config()
            
            # Perform log rotation based on configuration
            LogManager.perform_log_rotation(job_id)
    
    def add_job(self, job_id: str, module: str, config_file: str, 
                interval_type: str = 'minutes', interval_value: int = 60,
                cron_expression: str = None, enabled: bool = True):
        """Add a new job to the registry."""
        job_config = {
            'module': module,
            'config_file': config_file,
            'interval_type': interval_type,
            'interval_value': interval_value,
            'enabled': enabled,
            'created': datetime.now().isoformat(),
            'status': 'idle'
        }
        
        if cron_expression:
            job_config['cron_expression'] = cron_expression
        
        jobs_registry[job_id] = job_config
        
        if enabled:
            self._schedule_job(job_id, job_config)
        
        self.save_jobs_config()
    
    def remove_job(self, job_id: str):
        """Remove a job from the registry and scheduler."""
        if job_id in jobs_registry:
            del jobs_registry[job_id]
            self.save_jobs_config()
        
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    
    def toggle_job(self, job_id: str):
        """Enable/disable a job."""
        if job_id not in jobs_registry:
            return False
        
        config = jobs_registry[job_id]
        config['enabled'] = not config.get('enabled', False)
        
        if config['enabled']:
            self._schedule_job(job_id, config)
        else:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        
        self.save_jobs_config()
        return True
    
    def run_job_now(self, job_id: str):
        """Manually trigger a job to run immediately."""
        if job_id in jobs_registry:
            scheduler.add_job(
                func=self._execute_job,
                trigger='date',
                args=[job_id],
                id=f"{job_id}_manual"
            )
            return True
        return False

# Initialize job manager
job_manager = JobManager()

@app.route('/')
def index():
    """Main dashboard showing all jobs."""
    return render_template('index.html', 
                         jobs=jobs_registry, 
                         modules=job_manager.available_modules)

@app.route('/add_job', methods=['GET', 'POST'])
def add_job():
    """Add a new job."""
    if request.method == 'POST':
        job_id = request.form.get('job_id')
        module = request.form.get('module')
        config_file = request.form.get('config_file')
        interval_type = request.form.get('interval_type', 'minutes')
        interval_value = int(request.form.get('interval_value', 60))
        cron_expression = request.form.get('cron_expression')
        enabled = 'enabled' in request.form
        
        if job_id and module and config_file:
            try:
                job_manager.add_job(
                    job_id=job_id,
                    module=module,
                    config_file=config_file,
                    interval_type=interval_type,
                    interval_value=interval_value,
                    cron_expression=cron_expression,
                    enabled=enabled
                )
                flash(f'Job {job_id} added successfully!', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                flash(f'Error adding job: {e}', 'error')
        else:
            flash('Please fill in all required fields', 'error')
    
    return render_template('add_job.html', modules=job_manager.available_modules)

@app.route('/toggle_job/<job_id>')
def toggle_job(job_id):
    """Toggle job enabled/disabled status."""
    if job_manager.toggle_job(job_id):
        status = 'enabled' if jobs_registry[job_id]['enabled'] else 'disabled'
        flash(f'Job {job_id} {status}', 'success')
    else:
        flash(f'Job {job_id} not found', 'error')
    return redirect(url_for('index'))

@app.route('/run_job/<job_id>')
def run_job(job_id):
    """Manually run a job."""
    if job_manager.run_job_now(job_id):
        flash(f'Job {job_id} triggered manually', 'success')
    else:
        flash(f'Job {job_id} not found', 'error')
    return redirect(url_for('index'))

@app.route('/remove_job/<job_id>')
def remove_job(job_id):
    """Remove a job."""
    job_manager.remove_job(job_id)
    flash(f'Job {job_id} removed', 'success')
    return redirect(url_for('index'))

@app.route('/api/jobs')
def api_jobs():
    """API endpoint to get job status."""
    return jsonify(jobs_registry)

@app.route('/logs/<job_id>')
def view_logs(job_id):
    """View logs for a specific job."""
    job = jobs_registry.get(job_id, {})
    log_files = LogManager.get_log_files_for_job(job_id)
    
    # Get the latest log content if available
    latest_log_content = ""
    if log_files:
        latest_log_content = LogManager.read_log_file(log_files[0]['path'])
    
    return render_template('logs.html', 
                         job_id=job_id, 
                         job=job, 
                         log_files=log_files,
                         latest_log_content=latest_log_content)

@app.route('/logs/<job_id>/<filename>')
def view_log_file(job_id, filename):
    """View a specific log file."""
    log_file_path = os.path.join(LOG_DIRECTORY, filename)
    
    # Security check - ensure filename belongs to the job
    if not filename.startswith(f"{job_id}_") or not filename.endswith('.log'):
        flash('Invalid log file requested', 'error')
        return redirect(url_for('view_logs', job_id=job_id))
    
    if not os.path.exists(log_file_path):
        flash('Log file not found', 'error')
        return redirect(url_for('view_logs', job_id=job_id))
    
    log_content = LogManager.read_log_file(log_file_path)
    job = jobs_registry.get(job_id, {})
    
    return render_template('log_file.html',
                         job_id=job_id,
                         job=job,
                         filename=filename,
                         log_content=log_content)

@app.route('/api/logs/<job_id>/cleanup', methods=['POST'])
def cleanup_logs(job_id):
    """Clean up old log files for a job."""
    try:
        keep_count = int(request.json.get('keep_count', 5))
        LogManager.cleanup_old_logs(job_id, keep_count)
        return jsonify({'success': True, 'message': f'Cleaned up logs for {job_id}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/logs')
def admin_logs():
    """Admin page for log management."""
    rotation_info = LogManager.get_rotation_info()
    return render_template('admin_logs.html', rotation_info=rotation_info)

@app.route('/api/logs/rotation/info')
def rotation_info_api():
    """Get log rotation information via API."""
    return jsonify(LogManager.get_rotation_info())

@app.route('/api/logs/rotation/perform', methods=['POST'])
def perform_rotation():
    """Manually trigger log rotation."""
    try:
        job_id = request.json.get('job_id') if request.is_json else None
        results = LogManager.perform_log_rotation(job_id)
        return jsonify({
            'success': True, 
            'message': f'Rotation complete: {results["age_removed"]} old files, {results["count_removed"]} excess files removed',
            'results': results
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    # Create required directories if they don't exist
    os.makedirs('templates', exist_ok=True)
    LogManager.ensure_log_directory()
    
    # Perform initial log rotation on startup
    print("Performing initial log rotation...")
    rotation_results = LogManager.perform_log_rotation()
    if rotation_results['age_removed'] > 0 or rotation_results['count_removed'] > 0:
        print(f"Log rotation: removed {rotation_results['age_removed']} old files, "
              f"{rotation_results['count_removed']} excess files")
    
    app.run(debug=True, host='0.0.0.0', port=8000)
