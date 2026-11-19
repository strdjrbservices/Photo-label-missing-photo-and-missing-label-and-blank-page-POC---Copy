# AppraisalGuard: MISMO XML & Computer Vision Quality Audit

Automated quality control and data integrity audit of **MISMO Appraisal XML reports** and their embedded/accompanying documents using **Django**, **Python**, **OpenCV**, and **PyMuPDF**.

Includes a modern **Django Web Application UI** and is pre-configured for instant **PythonAnywhere** deployment.

---

## 🎯 System Capabilities

### 1. Photo and Label Extraction & Inventory
- **Photo Extraction**: Extracts embedded photos from report photo pages across both 3-photo and 6-photo grid layouts along with image dimensions and quality metrics, saving images directly to disk.
- **Label Mapping**: Matches each photo slot directly to the appraiser's text label (e.g. `Subject Front`, `Subject Rear`, `Living Room`, `Kitchen`, `Full Bathroom 1`).
- **Bed/Bath Count Validation**: Identifies and counts bedroom and bathroom photos directly from extracted labels to compare against XML records.

### 2. Missing Label Detection for Photos
- **Unlabeled Photo Detection**: Detects photo slots where an image is attached but the appraiser omitted the text label (or left it empty/whitespace).
- **Empty Slot Identification**: Identifies placeholders marked as `Blank` or slots where a label is declared but no photo is attached (`MISSING_PHOTO`).

### 3. Blank Page Detection (OpenCV)
- **Header/Footer-Stripped Inspection**: Isolates the core body region of each page to prevent boilerplate headers (e.g. "Serial#", form numbers, software watermark, borrower names) from causing false negatives.
- **Edge & Texture Analysis**:
  - **Laplacian Variance**: Measures texture, detail, and visual sharpness.
  - **Canny Edge Density**: Calculates the proportion of edge pixels in the page body.
  - **Non-White Pixel Ratio**: Detects the percentage of content pixels vs empty paper background.
- **Classification**: Categorizes pages into `COMPLETELY_BLANK`, `TEMPLATE_HEADER_ONLY_BLANK`, `LOW_CONTENT_BLANK`, or `NON_BLANK`.

---

## 🌐 Running the Django Web UI (Local Development)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Database Migrations
```bash
python manage.py migrate
```

### 3. Launch Development Server
```bash
python manage.py runserver
```

Open your browser and navigate to:
**`http://127.0.0.1:8000/`**

### Web UI Features:
- **Interactive Dashboard**: View real-time platform metrics, previous audits, and status indicators.
- **Upload or Choose Sample**: Drag-and-drop your XML/PDF files, or select from pre-loaded sample reports with 1-click execution.
- **Photo Gallery**: Browse extracted photos with category filter chips (`Exterior Front`, `Kitchen`, `Bedrooms`, etc.), blur scores, and modal lightbox zoom.
- **Audit Findings**: Dedicated tabs for missing labels, bed/bath discrepancy alerts, and OpenCV blank page edge metrics.
- **One-Click Downloads**: Direct download links for styled multi-tab Excel reports (`.xlsx`) and structured JSON files.

---

## ☁️ Deploying to PythonAnywhere

A complete turnkey deployment configuration is provided. See [`DEPLOYMENT_PYTHONANYWHERE.md`](file:///DEPLOYMENT_PYTHONANYWHERE.md) for the detailed step-by-step tutorial.

### Quick Deployment Summary:
1. Clone or upload your repository to PythonAnywhere.
2. In the PythonAnywhere Bash console, run:
   ```bash
   chmod +x deploy_pythonanywhere.sh
   ./deploy_pythonanywhere.sh
   ```
3. In the PythonAnywhere **Web** tab:
   - Set Virtualenv path to `/home/<username>/.virtualenvs/appraisal-venv`.
   - Set Static Files mappings:
     - `/static/` &rarr; `/home/<username>/appraisal-audit/staticfiles`
     - `/media/` &rarr; `/home/<username>/appraisal-audit/media`
   - Paste `pythonanywhere_wsgi.py` contents into your WSGI configuration file.
   - Click the green **Reload** button!

---

## 💻 Command-Line Interface (CLI)

You can also run the audit pipeline directly from the terminal:

### 1. Full Audit on a Report (Generates Excel by Default)
```powershell
python run_poc.py "2611-00509(1004).xml"
```

### 2. Save Analysis to JSON & Excel with Photo Paths
```powershell
python run_poc.py "2611-00509(1004).xml" --save-json
```

### 3. Fast Mode (Targeted Tasks)
```powershell
# Only detect blank pages with OpenCV (~2.5s)
python run_poc.py -t blank "2611-00407(1004+1007).xml"

# Only extract photos and check missing labels (~0.8s)
python run_poc.py -t photos "2611-00509(1004).xml"
```

### 4. Batch Analysis Across All Reports
```powershell
python run_poc.py --all --save-json
```

---

## 🏗️ Project Structure

```
├── appraisal_analyzer/                 # Modular Computer Vision & XML Parser package
│   ├── xml_parser.py                   # MISMO 2.6 XML metadata & base64 PDF extractor
│   ├── photo_verifier.py               # Photo and label extractor & missing label detector
│   ├── blank_detector.py               # OpenCV Laplacian & Canny blank page detector
│   ├── excel_generator.py              # Multi-tab styled Excel report generator with photo paths
│   └── pipeline.py                     # Unified end-to-end execution pipeline
├── appraisal_web/                      # Django project configuration
│   ├── settings.py                     # Settings configured for SQLite, Static & Media
│   ├── urls.py                         # Root URL dispatcher
│   └── wsgi.py                         # WSGI entrypoint
├── audit_app/                          # Core Django Audit application
│   ├── models.py                       # ReportAudit, AuditPhotoSlot, AuditBlankPage models
│   ├── views.py                        # Dashboard, audit execution, photo gallery & report views
│   ├── forms.py                        # Upload & sample report selection forms
│   ├── services.py                     # Pipeline orchestration and DB persistence service
│   ├── urls.py                         # Application routes
│   └── admin.py                        # Django Admin integration
├── templates/                          # Responsive Bootstrap 5 templates
│   ├── base.html                       # Global layout, navbar & styling
│   └── audit_app/
│       ├── index.html                  # Dashboard & audit execution center
│       └── detail.html                 # Tabbed audit report with photo gallery & metrics
├── pythonanywhere_wsgi.py              # Ready-to-copy PythonAnywhere WSGI configuration
├── deploy_pythonanywhere.sh             # Automated PythonAnywhere setup script
├── DEPLOYMENT_PYTHONANYWHERE.md         # Step-by-step PythonAnywhere deployment guide
├── requirements.txt                    # Project dependencies (with opencv-python-headless)
├── run_poc.py                          # CLI runner for terminal execution
└── manage.py                           # Django CLI management utility
```
