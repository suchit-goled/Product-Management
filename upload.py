"""
Authenticated CLI client for Product Catalog Image Upload.
Signs into session, retrieves CSRF token, and performs an authorized upload.
"""
import sys
import os
import requests
from PIL import Image

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = os.getenv("CATALOG_URL", "http://127.0.0.1:5000")
USERNAME = os.getenv("CATALOG_USER", "editor")
PASSWORD = os.getenv("CATALOG_PASS", "")
if not PASSWORD:
    print("Error: Set CATALOG_PASS environment variable before running upload.py")
    sys.exit(1)

session = requests.Session()
# Obtain guest CSRF token from login page / auth endpoint
me = session.get(f"{BASE_URL}/gw/auth/me").json()
csrf = me.get("csrf_token", "")

login_res = session.post(
    f"{BASE_URL}/gw/auth/login",
    json={"identifier": USERNAME, "password": PASSWORD},
    headers={"X-CSRF-Token": csrf}
)
if login_res.status_code != 200:
    print("Authentication failed:", login_res.status_code, login_res.text)
    sys.exit(1)

csrf = login_res.json().get("csrf_token", csrf)

image_path = sys.argv[1] if len(sys.argv) > 1 else None
temp_created = False
if not image_path or not os.path.exists(image_path):
    print("Creating temporary test image...")
    image_path = "temp_catalog_upload_sample.jpg"
    Image.new("RGB", (400, 400), color=(37, 99, 235)).save(image_path, "JPEG")
    temp_created = True

try:
    with open(image_path, "rb") as img_file:
        res = session.post(
            f"{BASE_URL}/upload",
            files={"image": img_file},
            data={"save_immediately": "true"},
            headers={"X-CSRF-Token": csrf}
        )
        print(f"Status: {res.status_code}")
        print(res.json())
finally:
    session.post(f"{BASE_URL}/gw/auth/logout", headers={"X-CSRF-Token": csrf})
    if temp_created and os.path.exists(image_path):
        os.remove(image_path)
