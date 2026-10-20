# Suchit — AI Product Catalog Generator

[![Python 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Flask 3.1](https://img.shields.io/badge/Flask-3.1-black.svg)](https://palletsprojects.com/p/flask/)
[![Google GenAI](https://img.shields.io/badge/Google%20GenAI-Gemini%202.5%20%2F%202.0-4285F4.svg)](https://ai.google.dev/)
[![ReportLab 5.0](https://img.shields.io/badge/PDF-ReportLab%205.0-red.svg)](https://www.reportlab.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Suchit** is an enterprise-ready, multimodal AI-powered product cataloging engine designed to transform product photographs, packaging labels, and retail images into polished, production-ready e-commerce catalog entries.

Built on Python, Flask, Pillow, and Google's Gemini Multimodal models, Suchit automates visual inspection, OCR text extraction, marketing copy synthesis, and multi-channel catalog publishing with professional PDF, CSV, and JSON exports.

---

## 🌟 Key Highlights & Modernized Features

- **Multimodal AI Vision & OCR Extraction**: Seamlessly integrates with Google GenAI (`gemini-2.5-flash`, `gemini-2.0-flash`) to identify brand names, packaging text, physical dimensions, model numbers, and technical specifications directly from images.
- **Resilient Offline Fallback**: If an API key is missing or invalid, Suchit never crashes or blocks workflows. It gracefully generates a structured local catalog draft from image metadata and filename heuristics, alerting the user to enter their key in Settings.
- **Pillow Image Preprocessing**: Automatically corrects smartphone EXIF orientations (`ImageOps.exif_transpose`), enforces file integrity via `Image.verify()`, optimizes oversized dimensions, and prevents malicious file uploads.
- **Side-by-Side Review & Refine Studio**: Provides an interactive side-by-side editing workspace with sticky image inspection, dynamic feature list editors, key-value specifications tables, and clear badges distinguishing verified packaging facts from AI-generated suggestions.
- **Professional Multi-Format Exports**:
  - **PDF Catalog Book & Spec Sheets**: Typeset documents generated via ReportLab featuring brand watermarks, high-res photos, clean specification tables, and dynamic "Page X of Y" canvas numbering.
  - **CSV Spreadsheets**: Encoded with UTF-8 BOM (`utf-8-sig`) for immediate, uncorrupted opening in Microsoft Excel and Google Sheets with special currency symbols (₹, $, €).
  - **Structured JSON Feeds**: Clean, nested JSON compatible with modern headless CMS platforms (Shopify, WooCommerce, Amazon).
- **Modern Restrained UI**: Designed with clean typography, slate neutrals (`#f8fafc`), deep indigo accents (`#2563eb`), live system health pills, metrics overview cards, search & filter toolbars, and responsive grid/table views.
- **Persistent SQLite Database**: Resilient database layer with automatic non-destructive schema migrations and indexes on `id`, `category`, and `brand`.

---

## 🏗️ Repository Architecture

```
promothon-main/
│
├── app.py                      # Main Flask application & REST endpoints
├── config.py                   # Environment configuration with absolute paths
├── database.py                 # SQLite database layer with auto-migration
├── products.db                 # Persistent SQLite database storage
│
├── services/                   # Modular service layer
│   ├── gemini_service.py       # Google GenAI integration & offline fallback
│   ├── image_service.py        # Pillow validation, sanitization & EXIF correction
│   ├── pdf_service.py          # ReportLab single & multi-page PDF generator
│   └── export_service.py       # UTF-8 BOM CSV & JSON catalog serializers
│
├── static/                     # Web application static assets
│   ├── css/style.css           # Modern, responsive design system
│   ├── js/script.js            # Reactive SPA catalog browser & workflow manager
│   └── uploads/                # Processed product image storage
│
├── templates/                  # Jinja2 templates
│   └── index.html              # Suchit Catalog Studio workspace UI
│
├── tests/                      # Automated test suite
│   └── test_suchit_catalog.py  # 14 comprehensive unit & integration tests
│
├── upload.py                   # CLI tool to upload & ingest product images
├── get.py                      # CLI tool to list all catalog items
├── getspci.py                  # CLI tool to inspect a specific product by ID
├── put_update.py               # CLI tool to update an existing product record
└── del.py                      # CLI tool to delete a product by ID
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Google Gemini API key (optional for offline fallback, get one free at [Google AI Studio](https://aistudio.google.com))

### 2. Setup Virtual Environment & Dependencies
```bash
# Activate your virtual environment
.\venv\Scripts\activate   # On Windows
# source venv/bin/activate # On Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create or verify `.env` in the project root:
```env
GEMINI_API_KEY=your_gemini_api_key_here
SECRET_KEY=suchit-catalog-secret-key-2026
DATABASE=products.db
UPLOAD_FOLDER=static/uploads
```
*(Note: You can also configure or update your Gemini API key anytime directly inside the web UI Settings tab!)*

### 4. Launch the Web Application
```bash
python app.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5000
```

---

## 📡 REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the Suchit Catalog Studio interactive workspace |
| `POST` | `/upload` | Ingests product image via multipart `image`, runs Pillow optimization & Gemini extraction |
| `GET` | `/products` | Retrieves all products. Supports `?search=...`, `?category=...`, `?brand=...`, `?sort=...` |
| `POST` | `/product` | Creates a new product record from JSON payload |
| `GET` | `/product/<id>` | Retrieves full product details by ID |
| `PUT` | `/product/<id>` | Updates an existing product record with JSON payload |
| `DELETE` | `/product/<id>` | Deletes product record by ID |
| `GET` | `/export/pdf` | Downloads comprehensive multi-page catalog PDF book |
| `GET` | `/export/pdf/<id>` | Downloads single-product PDF specification sheet |
| `GET` | `/export/csv` | Downloads CSV spreadsheet with UTF-8 BOM encoding |
| `GET` | `/export/json` | Downloads structured JSON feed |
| `GET` | `/api/stats` | Returns real-time database metrics (total items, brands, categories) |
| `GET` | `/api/health` | Returns application health and storage diagnostics |
| `POST` | `/api/settings/test-key` | Tests connectivity and latency of a Gemini API key |
| `POST` | `/api/settings` | Updates and persists runtime settings to `.env` |

---

## 💻 Command Line Utilities

The project includes modular command-line scripts for terminal operations:

```bash
# 1. Ingest an image into the catalog
python upload.py path/to/product_image.jpg

# 2. List all catalog products
python get.py

# 3. View details of a specific product
python getspci.py 3

# 4. Update product details
python put_update.py

# 5. Delete a product
python del.py 20
```

---

## 🧪 Automated Testing

Execute the test suite covering the full API, image processing, database migration, and export pipeline:

```bash
python -m unittest tests/test_suchit_catalog.py -v
```

All 14 tests run in under 6 seconds, validating:
- UI branding and static asset resolution
- Health and diagnostics endpoints
- Full CRUD database lifecycle
- Backward compatibility with legacy comma-separated features
- ReportLab PDF generation (single-sheet & full catalog book)
- UTF-8 BOM CSV spreadsheet encoding
- Pillow image validation and fallback handling on missing/invalid API keys

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).

---
*Suchit AI Product Catalog Generator • Intelligent Multimodal Cataloging Engine • v2.0*
