import sys
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

url = "http://127.0.0.1:5000/products"

response = requests.get(url)

if response.status_code == 200:
    print("All Products in Suchit Catalog:")
    products = response.json()
    print(f"Total Products: {len(products)}")
    for p in products:
        print(f" - [#{p.get('id')}] {p.get('product_name')} ({p.get('brand')}) - {p.get('price')}")
else:
    print(f"Failed to fetch products. Status code: {response.status_code}")
