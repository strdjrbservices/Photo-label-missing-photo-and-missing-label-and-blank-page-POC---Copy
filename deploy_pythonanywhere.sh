#!/bin/bash
# ==============================================================================
# Automated PythonAnywhere Setup Script for AppraisalGuard Django Application
# ==============================================================================

set -e

VENV_DIR="$HOME/.virtualenvs/appraisal-venv"

echo "=== [1/5] Checking Python & Virtualenv ==="
mkdir -p "$HOME/.virtualenvs"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment 'appraisal-venv' with Python 3.10..."
    python3.10 -m venv "$VENV_DIR"
fi

echo "Activating virtual environment ($VENV_DIR)..."
source "$VENV_DIR/bin/activate"

echo "=== [2/5] Installing Dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [3/5] Applying Database Migrations ==="
python manage.py migrate

echo "=== [4/5] Collecting Static Files ==="
python manage.py collectstatic --noinput

echo "=== [5/5] Ensuring Media Directories Exist ==="
mkdir -p media/uploads media/extracted_photos media/audit_reports media/blank_previews

echo ""
echo "=========================================================================="
echo " Setup complete! Next steps in your PythonAnywhere 'Web' tab:"
echo " 1. Set Virtualenv path to: /home/$USER/.virtualenvs/appraisal-venv"
echo " 2. In Static Files section, add:"
echo "    URL: /static/  -> Directory: $PWD/staticfiles"
echo "    URL: /media/   -> Directory: $PWD/media"
echo " 3. Edit WSGI configuration file and point to: $PWD"
echo " 4. Click the green 'Reload <username>.pythonanywhere.com' button"
echo "=========================================================================="
