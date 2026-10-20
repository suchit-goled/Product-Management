"""
Suchit Catalog - Export Service
Handles CSV and JSON exports with proper character encoding (UTF-8 with BOM for Excel),
clean delimiters, and structured metadata.
"""
import csv
import io
import json
import datetime


def export_products_csv(products: list) -> bytes:
    """
    Exports a list of product dictionaries to CSV bytes with UTF-8 BOM encoding.
    Ensures complex fields (features, specifications, selling points, tags) are
    formatted cleanly for spreadsheet viewing and editing.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    headers = [
        "ID",
        "Product Name",
        "Brand",
        "Model",
        "Category",
        "Price",
        "Dimensions",
        "Short Description",
        "Description",
        "Features",
        "Specifications",
        "Selling Points",
        "Tags",
        "SEO Title",
        "SEO Description",
        "Image Path",
        "Created At"
    ]
    writer.writerow(headers)

    for p in products:
        # Format features as newline-separated bullet list
        features = p.get("features", [])
        if isinstance(features, list):
            feat_str = "\n".join(f"• {f}" for f in features)
        else:
            feat_str = str(features or "")

        # Format specs as key: value lines
        specs = p.get("specifications", {})
        if isinstance(specs, dict):
            specs_str = "\n".join(f"{k}: {v}" for k, v in specs.items())
        else:
            specs_str = str(specs or "")

        # Format selling points
        usp = p.get("selling_points", [])
        if isinstance(usp, list):
            usp_str = "\n".join(f"✓ {u}" for u in usp)
        else:
            usp_str = str(usp or "")

        # Format tags
        tags = p.get("tags", [])
        if isinstance(tags, list):
            tags_str = ", ".join(tags)
        else:
            tags_str = str(tags or "")

        row = [
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
        writer.writerow(row)

    # Encode with utf-8-sig so Excel recognizes UTF-8 (e.g. ₹ rupee symbol)
    return output.getvalue().encode("utf-8-sig")


def export_products_json(products: list) -> str:
    """Exports products as a formatted JSON document with catalog metadata."""
    payload = {
        "catalog_name": "Suchit Product Catalog",
        "export_timestamp": datetime.datetime.now().isoformat(),
        "total_products": len(products),
        "products": products
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
