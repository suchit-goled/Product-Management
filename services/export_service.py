"""
Suchit Catalog - Export Service
Handles CSV and JSON exports with UTF-8 BOM encoding, RFC 4180 quoting,
and Spreadsheet Formula / DDE Injection mitigation across every CSV cell.
"""
import csv
import io
import json
import datetime
from services.security_service import sanitize_csv_cell


def export_products_csv(products: list) -> bytes:
    """Exports products to RFC 4180 CSV with UTF-8 BOM and formula injection protection."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    headers = [
        "ID", "Product Name", "Brand", "Model", "Category", "Price", "Dimensions",
        "Short Description", "Description", "Features", "Specifications",
        "Selling Points", "Tags", "SEO Title", "SEO Description", "Image Path", "Created At"
    ]
    writer.writerow(headers)

    for p in products:
        features = p.get("features", [])
        feat_str = "\n".join(f"• {f}" for f in features) if isinstance(features, list) else str(features or "")

        specs = p.get("specifications", {})
        specs_str = "\n".join(f"{k}: {v}" for k, v in specs.items()) if isinstance(specs, dict) else str(specs or "")

        usp = p.get("selling_points", [])
        usp_str = "\n".join(f"✓ {u}" for u in usp) if isinstance(usp, list) else str(usp or "")

        tags = p.get("tags", [])
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags or "")

        raw_row = [
            p.get("id", ""),
            p.get("product_name", ""),
            p.get("brand", ""),
            p.get("model", ""),
            p.get("category", ""),
            p.get("price", ""),
            p.get("dimensions", ""),
            p.get("short_description", ""),
            p.get("description", ""),
            feat_str,
            specs_str,
            usp_str,
            tags_str,
            p.get("seo_title", ""),
            p.get("seo_description", ""),
            p.get("image_path", ""),
            p.get("created_at", "")
        ]
        writer.writerow([sanitize_csv_cell(cell) for cell in raw_row])

    return output.getvalue().encode("utf-8-sig")


def export_products_json(products: list) -> str:
    """Exports products as formatted JSON feed with catalog metadata."""
    payload = {
        "catalog_name": "Suchit Product Catalog",
        "export_timestamp": datetime.datetime.now().isoformat(),
        "total_items": len(products),
        "products": products
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
