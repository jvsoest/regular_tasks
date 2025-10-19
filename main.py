import os
import sys
import importlib
import json
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import atexit

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'  # Change this in production

# Global scheduler
scheduler = BackgroundScheduler()
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# Job registry to store job configurations
JOBS_CONFIG_FILE = 'jobs_config.json'
jobs_registry: Dict[str, Dict[str, Any]] = {}

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
        """Execute a job module."""
        try:
            config = jobs_registry.get(job_id)
            if not config:
                print(f"Job {job_id} not found in registry")
                return
            
            module_name = config['module']
            config_file = config.get('config_file')
            
            # Update last run time
            jobs_registry[job_id]['last_run'] = datetime.now().isoformat()
            jobs_registry[job_id]['status'] = 'running'
            self.save_jobs_config()
            
            # Import and run the module
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            
            module_path = f"{module_name}.run"
            module = importlib.import_module(module_path)
            
            if hasattr(module, 'main') and config_file:
                # Execute with config file
                original_argv = sys.argv
                sys.argv = ['run.py', config_file]
                module.main()
                sys.argv = original_argv
            elif hasattr(module, 'migrate') and config_file:
                # For email_move type modules
                from . import load_config
                cfg = load_config(config_file)
                module.migrate(cfg)
            else:
                print(f"Module {module_name} doesn't have expected entry points")
                return
            
            # Update success status
            jobs_registry[job_id]['status'] = 'success'
            jobs_registry[job_id]['last_success'] = datetime.now().isoformat()
            
        except Exception as e:
            print(f"Error executing job {job_id}: {e}")
            traceback.print_exc()
            jobs_registry[job_id]['status'] = 'error'
            jobs_registry[job_id]['last_error'] = str(e)
        finally:
            self.save_jobs_config()
    
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
    return render_template('logs.html', job_id=job_id, job=job)

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=8000)
