# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# PythonAnywhere WSGI configuration for AppraisalGuard Django Application
#
# Instructions:
# 1. In your PythonAnywhere dashboard -> "Web" tab.
# 2. Click on the WSGI configuration file link (/var/www/<your-username>_pythonanywhere_com_wsgi.py).
# 3. Replace its contents with this file (updating '<your-username>' with your actual username).
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

import os
import sys

# Replace '<your-username>' and the folder name with your actual PythonAnywhere setup
# For example: '/home/johndoe/appraisal-audit'
username = '<your-username>'
project_folder_name = 'appraisal-audit'

project_home = f'/home/{username}/{project_folder_name}'

if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment variable to tell Django where settings are located
os.environ['DJANGO_SETTINGS_MODULE'] = 'appraisal_web.settings'
os.environ['DJANGO_DEBUG'] = 'False'

# Load the Django WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
