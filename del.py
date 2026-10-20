import sys
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Specify product ID to delete (e.g. from CLI argument)
product_id = sys.argv[1] if len(sys.argv) > 1 else None

if not product_id:
    print("Usage: python del.py <product_id>")
    print("Example: python del.py 13")
    sys.exit(0)

url = f"http://127.0.0.1:5000/product/{product_id}"
response = requests.delete(url)

if response.status_code == 200:
    print(f"Product #{product_id} deleted successfully from Suchit Catalog!")
else:
    print(f"Failed to delete product #{product_id}. Status code: {response.status_code}, error: {response.text}")
