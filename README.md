# Product Catalog

[![Python 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Flask 3.1](https://img.shields.io/badge/Flask-3.1-black.svg)](https://palletsprojects.com/p/flask/)
[![Groq AI](https://img.shields.io/badge/Groq%20AI-Llama%204%20Scout%20%2F%20Llama%203.3-f55036.svg)](https://groq.com/)
[![Google GenAI](https://img.shields.io/badge/Google%20GenAI-Gemini%202.5%20%2F%202.0-4285F4.svg)](https://ai.google.dev/)
[![ReportLab 5.0](https://img.shields.io/badge/PDF-ReportLab%205.0-red.svg)](https://www.reportlab.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Product Catalog** is an enterprise-ready, multimodal AI-powered product cataloging platform designed to transform product photographs, packaging labels, and product briefs into polished, production-ready e-commerce catalog entries.

Built on Python, Flask, Pillow, Groq AI, and Google Gemini Multimodal models, Product Catalog automates visual inspection, OCR text extraction, marketing copy synthesis, and multi-channel catalog publishing with professional PDF, CSV, and JSON exports.

---

## 🌟 Key Highlights & Features

- **Multimodal AI Vision & Brief Synthesis**: Integrates with server-side Groq (`meta-llama/llama-4-scout-17b-16e-instruct`, `qwen/qwen3.8-27b`, `llama-3.3-70b-versatile`) and Google GenAI (`gemini-2.5-flash`, `gemini-2.0-flash`) to generate brand names, pricing, specifications, features, and SEO fields from images or text briefs.
- **Resilient Offline Fallback**: If an AI key is missing or unavailable, Product Catalog gracefully prepares a structured local catalog draft without blocking workflows or exposing server credentials.
- **Pillow Image Preprocessing**: Automatically corrects smartphone EXIF orientations (`ImageOps.exif_transpose`), strips embedded EXIF/XMP metadata, enforces file integrity via `Image.verify()`, and creates WebP + JPEG assets.
- **Side-by-Side Review & Refine Studio**: Provides an interactive editing workspace with dynamic feature list editors, key-value specifications tables, and SEO controls.
- **Professional Multi-Format Exports**:
  - **PDF Catalog Book & Spec Sheets**: Typeset documents generated via ReportLab with specification tables and dynamic "Page X of Y" canvas numbering.
  - **CSV Spreadsheets**: Encoded with UTF-8 BOM (`utf-8-sig`) and formula-injection protection.
  - **Structured JSON Feeds**: Clean, nested JSON compatible with headless CMS platforms.
- **Role-Based Security & Data Privacy**: Opaque server-side sessions, HMAC CSRF tokens, Origin enforcement, strict CSP (zero external trackers), zero frontend API keys, and server-side ACID snapshots.

---

## 🏗️ Repository Architecture

```
promothon-main/
│
├── app.py                      # Main Flask application & REST/BFF endpoints
├── config.py                   # Environment configuration with absolute paths
├── database.py                 # SQLite WAL database layer with auto-migration
├── products.db                 # Persistent SQLite database storage
│
├── services/                   # Modular service layer
│   ├── groq_service.py         # Groq Vision & LLM catalog generation
│   ├── gemini_service.py       # Google GenAI integration & offline fallback
│   ├── image_service.py        # Pillow validation, sanitization & EXIF scrubbing
│   ├── pdf_service.py          # ReportLab single & multi-page PDF generator
│   ├── export_service.py       # UTF-8 BOM CSV & JSON catalog serializers
│   ├── cache_service.py        # L1/L2 cache, opaque sessions & rate limiter
│   ├── queue_service.py        # Persistent job queue & outbox
│   ├── worker_service.py       # Background email & snapshot worker
│   ├── backup_service.py       # Server-side SQLite online backups
│   └── security_service.py     # CSRF, Luhn, pricing & path safety
│
├── static/                     # Web application static assets
│   ├── css/style.css           # Responsive design system
│   ├── js/app.js               # Public & authenticated viewer client layer
│   ├── js/editor.js            # Role-gated AI Studio & CRUD module
│   ├── js/admin.js             # Role-gated Admin operational telemetry
│   └── uploads/                # Processed product image storage
│
├── templates/                  # Jinja2 templates
│   ├── index.html              # Product Catalog workspace UI
│   ├── 404.html                # Branded 404 page
│   └── 500.html                # Branded 500 page
│
├── tests/                      # Automated test suite
│   └── test_product_catalog.py # Comprehensive security & functional tests
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
- Groq API key and/or Google Gemini API key (optional for offline fallback)

### 2. Setup Virtual Environment & Dependencies
```bash
.\.venv\Scripts\activate  # On Windows
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create or verify `.env` in `promothon-main/`:
```env
GROQ_API_KEY=your_groq_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
SECRET_KEY=your_64_char_hex_secret_key_here
DATABASE=products.db
UPLOAD_FOLDER=static/uploads
```
*(Note: API keys and secrets are strictly managed server-side via environment variables / `.env` and are never exposed or editable through the web frontend.)*

### 4. Launch the Web Application
```bash
python app.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5000
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the Product Catalog interactive workspace |
| `POST` | `/gw/studio/upload` | Ingests product image via multipart `image`, runs Pillow sanitization & AI extraction |
| `POST` | `/gw/studio/generate` | Generates structured catalog draft from a product text brief via Groq/Gemini |
| `GET` | `/products` | Retrieves catalog products (`?search=...`, `?category=...`, `?brand=...`, `?sort=...`) |
| `POST` | `/product` | Creates a new product record from JSON payload (Editor/Admin) |
| `GET` | `/product/<id>` | Retrieves product details by ID |
| `PUT` | `/product/<id>` | Updates an existing product record (Editor/Admin) |
| `DELETE` | `/product/<id>` | Deletes product record by ID (Editor/Admin) |
| `GET` | `/export/pdf` | Downloads comprehensive multi-page catalog PDF book |
| `GET` | `/export/pdf/<id>` | Downloads single-product PDF specification sheet |
| `GET` | `/export/csv` | Downloads CSV spreadsheet with UTF-8 BOM encoding |
| `GET` | `/export/json` | Downloads structured JSON feed |
| `GET` | `/api/stats` | Returns catalog summary metrics |
| `GET` | `/api/health` | Returns admin-only operational diagnostics (never exposes API keys) |
| `GET` | `/healthz` | Minimal public liveness probe revealing zero secrets |

---

## 🧪 Automated Testing

```bash
python -m unittest discover -s tests -v
```

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).

---
*Product Catalog • Intelligent Multimodal Cataloging Platform • v2.3.0*
