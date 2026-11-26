"""
Authenticated CLI client for deleting a catalog item securely.
"""
import sys
import os
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

product_id = sys.argv[1] if len(sys.argv) > 1 else None
if not product_id:
    print("Usage: python del.py <product_id>")
    sys.exit(0)

BASE_URL = os.getenv("CATALOG_URL", "http://127.0.0.1:5000")
USERNAME = os.getenv("CATALOG_USER", "editor")
PASSWORD = os.getenv("CATALOG_PASS", "")
if not PASSWORD:
    print("Error: Set CATALOG_PASS environment variable before running del.py")
    sys.exit(1)

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
response = session.delete(f"{BASE_URL}/product/{product_id}", headers={"X-CSRF-Token": csrf})
print(f"Status: {response.status_code}", response.json())
session.post(f"{BASE_URL}/gw/auth/logout", headers={"X-CSRF-Token": csrf})
