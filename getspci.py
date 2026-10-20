import sys
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Ask user or default to product 3
product_id = sys.argv[1] if len(sys.argv) > 1 else "3"

url = f"http://127.0.0.1:5000/product/{product_id}"

response = requests.get(url)

if response.status_code == 200:
    p = response.json()
    print(f"Product Details [#{p.get('id')}]:")
    print(f"  Name:        {p.get('product_name')}")
    print(f"  Brand:       {p.get('brand')}")
    print(f"  Category:    {p.get('category')}")
    print(f"  Price:       {p.get('price')}")
    print(f"  Dimensions:  {p.get('dimensions')}")
    print(f"  Features:    {', '.join(p.get('features', []))}")
else:
    print(f"Failed to fetch product #{product_id}. Status code: {response.status_code}")
