# 🚀 PythonAnywhere Deployment Guide

This guide walks you through deploying the **AppraisalGuard MISMO XML & Computer Vision Django Application** to [PythonAnywhere](https://www.pythonanywhere.com/).

---

## 📋 Overview of What We Built

- **Django Web Framework**: Full MVC application with upload handling, database persistence, and background task execution.
- **Modern Responsive Web UI**:
  - Drag-and-drop file upload (`.xml`, `.pdf`) and 1-click sample report selector.
  - Property metadata dashboard (GLA, Appraised Value, XML Beds/Baths).
  - Photo Gallery with category chips (`Exterior Front`, `Living Room`, `Kitchen`, `Bedrooms`, etc.), blur score metrics, and modal zoom.
  - Missing Label & Missing Photo inspection cards.
  - OpenCV edge density and Laplacian blank page verification table with preview thumbnails.
  - Direct downloads for styled Excel audit workbooks (`.xlsx`) and structured JSON files.
- **PythonAnywhere Headless Optimization**: Configured with `opencv-python-headless` to eliminate missing X11/GUI display library dependencies (`libGL.so.1`).

---

## 🛠️ Step-by-Step Deployment Steps on PythonAnywhere

### Step 1: Upload Your Code to PythonAnywhere
You can either clone your Git repository or upload a ZIP file from your local machine:

#### Option A (Recommended): Git Clone
1. Open a **Bash console** on PythonAnywhere.
2. Clone your repository:
   ```bash
   git clone <your-git-repo-url> appraisal-audit
   cd appraisal-audit
   ```

#### Option B: Upload ZIP via Dashboard
1. Zip your project folder locally (excluding `.git` and `__pycache__`).
2. Go to the **Files** tab on PythonAnywhere and upload `appraisal-audit.zip`.
3. In a **Bash console**, unzip it:
   ```bash
   unzip appraisal-audit.zip -d appraisal-audit
   cd appraisal-audit
   ```

---

### Step 2: Run the Automated Setup Script
In your PythonAnywhere Bash console, simply run:
```bash
chmod +x deploy_pythonanywhere.sh
./deploy_pythonanywhere.sh
```

*Or perform the commands manually:*
```bash
# 1. Create and activate a Python 3.10 virtualenv
mkdir -p ~/.virtualenvs
python3.10 -m venv ~/.virtualenvs/appraisal-venv
source ~/.virtualenvs/appraisal-venv/bin/activate

# 2. Install dependencies (headless OpenCV avoids server GUI library errors)
pip install -r requirements.txt

# 3. Initialize SQLite database & migrations
python manage.py migrate

# 4. Collect static files
python manage.py collectstatic --noinput

# 5. Create media upload & preview directories
mkdir -p media/uploads media/extracted_photos media/audit_reports media/blank_previews
```

---

### Step 3: Configure the Web App on PythonAnywhere

1. Go to the **Web** tab on the PythonAnywhere dashboard.
2. Click **Add a new web app**.
3. Choose **Manual configuration** (do NOT choose Django, as you already have the existing project configured).
4. Select **Python 3.10** (matching your virtual environment).

#### A. Set the Virtualenv Path
In the **Virtualenv** section:
- Enter the path:
  ```
  /home/<your-username>/.virtualenvs/appraisal-venv
  ```
  *(Replace `<your-username>` with your actual PythonAnywhere account name).*

#### B. Configure Static and Media Files
Under the **Static files** section, add two mappings:

| URL | Directory |
| :--- | :--- |
| `/static/` | `/home/<your-username>/appraisal-audit/staticfiles` |
| `/media/` | `/home/<your-username>/appraisal-audit/media` |

*(This ensures all CSS, JS, extracted photos, and generated Excel files are served directly by PythonAnywhere's Nginx reverse proxy).*

#### C. Configure the WSGI File
In the **Code** section, click on the link next to **WSGI configuration file** (e.g. `/var/www/<your-username>_pythonanywhere_com_wsgi.py`).

Delete all default contents, paste the code below, and click **Save**:

```python
import os
import sys

# Replace '<your-username>' with your actual PythonAnywhere username
username = '<your-username>'
project_folder_name = 'appraisal-audit'

project_home = f'/home/{username}/{project_folder_name}'

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ['DJANGO_SETTINGS_MODULE'] = 'appraisal_web.settings'
os.environ['DJANGO_DEBUG'] = 'False'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

---

### Step 4: Reload and Test Your Web App
1. At the top of the **Web** tab, click the green **Reload `<your-username>.pythonanywhere.com`** button.
2. Visit `https://<your-username>.pythonanywhere.com`.
3. Try running an audit using the 1-click sample reports or uploading an appraisal XML/PDF!

---

## 🔒 Optional: Create Django Admin Superuser
To access the Django Admin portal (`/admin/`):
```bash
workon appraisal-venv
python manage.py createsuperuser
```
Follow the prompts to set up your username and password.
