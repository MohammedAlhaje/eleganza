#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict

# ===================== CONFIGURATION =====================
# 1. Main operations configuration (enable/disable steps)
OPERATIONS: Dict[str, bool] = {
    'django_checks': False,      # Run system checks
    'test': False,               # Run tests
    'clear_migrations': True,    # Clear old migrations
    'flush_db': True,            # Flush database (careful!)
    'make_migrations': True,     # Create new migrations
    'migrate': True,             # Apply migrations
    'create_superuser': True     # Create admin user
}

# 2. Superuser defaults (change as needed)
SUPERUSER: Dict[str, str] = {
    'username': 'admin',
    'email': 'admin@example.com',
    'password': 'Admin123',
}

# 3. Test configuration
TEST_CONFIG: Dict[str, bool] = {
    'parallel': True,
    'failfast': True,
    'coverage': False            # Set True to enable coverage.py
}

# 4. Migration configuration
MIGRATION_CONFIG: Dict[str, List[str]] = {
    'exclude_apps': []           # List apps to skip migration clearing
}

# 5. Prompt defaults configuration
PROMPT_DEFAULTS: Dict[str, bool] = {
    'flush_db': False,           # Default to N for flush database
    'create_superuser': True,    # Default to Y for create superuser
}
# =========================================================

def print_header(title: str) -> None:
    """Print formatted section header."""
    print(f"\n\033[1m=== {title.upper()} ===\033[0m")

def print_success(message: str) -> None:
    """Print success message."""
    print(f"\033[92m✓ {message}\033[0m")

def print_error(message: str) -> None:
    """Print error message."""
    print(f"\033[91m✗ {message}\033[0m", file=sys.stderr)

def print_warning(message: str) -> None:
    """Print warning message."""
    print(f"\033[93m⚠ {message}\033[0m")

def get_user_confirmation(prompt: str, default: bool) -> bool:
    """Get user confirmation with clear default indication."""
    default_str = 'Y' if default else 'N'
    options_str = '[Y/n]' if default else '[y/N]'
    full_prompt = f"{prompt} {options_str} (default is {default_str}): "
    
    response = input(full_prompt).strip().lower()
    if response == '':
        return default
    return response in ('y', 'yes')

def initialize_django() -> bool:
    """Initialize Django environment with improved error handling."""
    PROJECT_ROOT = Path(__file__).parent.parent
    sys.path.append(str(PROJECT_ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')

    print_header("Environment Check")
    print(f"Project root: {PROJECT_ROOT}")
    print("Python path:")
    for p in sys.path:
        print(f" - {p}")

    try:
        import django
    except ImportError:
        print_error("Django is not installed")
        print("Run: pip install django")
        return False

    try:
        django.setup()
        from django.conf import settings
        print_success("Django initialized")
        return True
    except ModuleNotFoundError as e:
        print_error(f"Missing dependency: {e.name}")
        print(f"Try: pip install {e.name.split('.')[0]}")
    except Exception as e:
        print_error(f"Django setup failed: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return False

def run_command(cmd: str, check: bool = True, env: dict = None) -> bool:
    """Execute shell command with better output handling."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent,
            env=env or os.environ
        )
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print_warning(result.stderr.strip())
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {cmd}")
        if e.stderr:
            print_error(e.stderr.strip())
        return False

def discover_local_apps() -> List[str]:
    """Get installed apps list excluding configured exceptions."""
    from django.conf import settings
    return [app for app in settings.INSTALLED_APPS 
            if app.startswith('eleganza.') and 
            app not in MIGRATION_CONFIG['exclude_apps']]

def django_checks() -> bool:
    """Run Django system checks."""
    print_header("Django System Checks")
    return run_command("python manage.py check --deploy")

def run_tests() -> bool:
    """Execute test suite with configured options."""
    print_header("Running Tests")
    cmd = "python manage.py test"
    if TEST_CONFIG['parallel']:
        cmd += " --parallel"
    if TEST_CONFIG['failfast']:
        cmd += " --failfast"
    if TEST_CONFIG['coverage']:
        cmd = "coverage run --source=. " + cmd
    return run_command(cmd)

def clear_migrations() -> bool:
    """Remove migration files with safety checks."""
    print_header("Clearing Migrations")
    for app in discover_local_apps():
        app_path = Path(app.replace('.', '/'))
        migrations_dir = app_path / "migrations"
        
        if not migrations_dir.exists():
            print_warning(f"No migrations dir: {app}")
            continue
            
        print(f"Processing: {app}")
        
        # Keep __init__.py and delete others
        deleted = 0
        for f in migrations_dir.glob("*.py"):
            if f.name != "__init__.py":
                f.unlink()
                deleted += 1
        
        # Clear __pycache__
        for pycache in app_path.rglob("__pycache__"):
            subprocess.run(f"rm -rf {pycache}", shell=True)
            deleted += 1
        
        print(f"Removed {deleted} files")
    
    return True

def flush_database() -> bool:
    """Flush the database with confirmation."""
    print_header("Flushing Database")
    default = PROMPT_DEFAULTS.get('flush_db', False)
    if not get_user_confirmation("Are you sure you want to flush the database?", default):
        print_warning("Database flush cancelled")
        return True
    return run_command("python manage.py flush --no-input")

def make_migrations() -> bool:
    """Create new migrations."""
    print_header("Creating Migrations")
    return run_command("python manage.py makemigrations")

def apply_migrations() -> bool:
    """Apply migrations to database."""
    print_header("Applying Migrations")
    return run_command("python manage.py migrate")

def create_superuser() -> bool:
    """Create admin user interactively."""
    print_header("Creating Superuser")
    default = PROMPT_DEFAULTS.get('create_superuser', True)
    if get_user_confirmation("Create default admin user?", default):
        env = os.environ.copy()
        env.update({
            "DJANGO_SUPERUSER_USERNAME": SUPERUSER['username'],
            "DJANGO_SUPERUSER_EMAIL": SUPERUSER['email'],
            "DJANGO_SUPERUSER_PASSWORD": SUPERUSER['password'],
        })
        return run_command("python manage.py createsuperuser --no-input", env=env)
    return run_command("python manage.py createsuperuser")

def main() -> None:
    """Main build pipeline."""
    print("\033[1m" + "="*40)
    print(" Django Build System")
    print("="*40 + "\033[0m")

    if not initialize_django():
        sys.exit(1)

    operations = [
        ('django_checks', django_checks),
        ('test', run_tests),
        ('clear_migrations', clear_migrations),
        ('flush_db', flush_database),
        ('make_migrations', make_migrations),
        ('migrate', apply_migrations),
        ('create_superuser', create_superuser)
    ]

    for op_name, op_func in operations:
        if not OPERATIONS.get(op_name, False):
            print_warning(f"Skipping {op_name} (disabled in config)")
            continue
            
        if not op_func():
            print_error(f"Build failed during: {op_name}")
            sys.exit(1)

    print_success("Build completed successfully!")

if __name__ == "__main__":
    main()