"""
Authenticated CLI client for updating a catalog item securely.
"""
import sys
import os
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = os.getenv("CATALOG_URL", "http://127.0.0.1:5000")
USERNAME = os.getenv("CATALOG_USER", "editor")
PASSWORD = os.getenv("CATALOG_PASS", "")
if not PASSWORD:
    print("Error: Set CATALOG_PASS environment variable before running put_update.py")
    sys.exit(1)

product_id = 3
updated_product_data = {
    "product_name": "boAt Airdopes 131 Pro",
    "brand": "boAt",
    "price": "₹1,499",
    "features": [
        "True Wireless Stereo",
        "ENx Environmental Noise Cancellation",
        "Up to 45 Hours Playback",
        "ASAP Fast Charge",
        "Bluetooth v5.3"
    ],
    "dimensions": "60 x 50 x 30 mm",
    "category": "Electronics & Audio"
}

session = requests.Session()
csrf = session.get(f"{BASE_URL}/gw/auth/me").json().get("csrf_token", "")
login = session.post(
    f"{BASE_URL}/gw/auth/login",
    json={"identifier": USERNAME, "password": PASSWORD},
    headers={"X-CSRF-Token": csrf}
)
if login.status_code != 200:
    print("Login failed:", login.text)
    sys.exit(1)

csrf = login.json().get("csrf_token", csrf)
response = session.put(
    f"{BASE_URL}/product/{product_id}",
    json=updated_product_data,
    headers={"X-CSRF-Token": csrf}
)
print(f"Status: {response.status_code}", response.json())
session.post(f"{BASE_URL}/gw/auth/logout", headers={"X-CSRF-Token": csrf})
