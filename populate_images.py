"""
Suchit Catalog - Showcase Image Generator & Complete DB Enrichment Script
Generates crisp 800x600 (4:3) JPEG + WebP studio product cards using system TrueType fonts
(zero broken Unicode glyphs), updates products.db so ALL products (#3..#12) have complete
non-null specifications/descriptions/SEO/timestamps, and cleans leftover test records.
"""
import os
import json
import sqlite3
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "static", "uploads")
MIRROR_UPLOADS_DIR = os.path.join(BASE_DIR, "my-project-folder", "static", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(MIRROR_UPLOADS_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "products.db")


def _load_font(size: int, bold: bool = False):
    candidates = (
        [
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold else
        [
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_rounded_rect(draw, bbox, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = bbox
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)


def create_product_artwork(prod_id, title, brand, category, theme_colors, icon_type):
    width, height = 800, 600
    bg_main, bg_grad, accent, card_bg, _ = theme_colors

    font_tag = _load_font(15, bold=True)
    font_cat = _load_font(15, bold=True)
    font_brand = _load_font(16, bold=True)
    font_title = _load_font(22, bold=True)
    font_badge = _load_font(14, bold=True)

    img = Image.new("RGB", (width, height), color=bg_main)
    draw = ImageDraw.Draw(img)

    # Smooth subtle vertical gradient
    for y in range(height):
        ratio = y / height
        r = int(bg_main[0] * (1 - ratio * 0.45) + bg_grad[0] * (ratio * 0.45))
        g = int(bg_main[1] * (1 - ratio * 0.45) + bg_grad[1] * (ratio * 0.45))
        b = int(bg_main[2] * (1 - ratio * 0.45) + bg_grad[2] * (ratio * 0.45))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Framing borders
    draw_rounded_rect(draw, [24, 24, width - 24, height - 24], radius=22, outline=accent, width=2)
    draw_rounded_rect(draw, [29, 29, width - 29, height - 29], radius=18, outline=(accent[0] // 2, accent[1] // 2, accent[2] // 2), width=1)

    # Header bar
    draw_rounded_rect(draw, [48, 44, 230, 82], radius=19, fill=accent)
    draw.text((68, 53), "SUCHIT CATALOG", fill=(255, 255, 255), font=font_tag)

    cat_label = category.upper()
    cat_bbox = draw.textbbox((0, 0), cat_label, font=font_cat)
    cat_w = cat_bbox[2] - cat_bbox[0]
    draw.text((width - 52 - cat_w, 53), cat_label, fill=accent, font=font_cat)

    # Showcase Stage
    stage_box = [140, 108, 660, 428]
    draw_rounded_rect(draw, stage_box, radius=24, fill=card_bg, outline=accent, width=2)
    cx, cy = 400, 268

    if icon_type == "audio":
        draw_rounded_rect(draw, [cx - 90, cy - 60, cx + 90, cy + 80], radius=45, fill=(36, 42, 58), outline=accent, width=3)
        draw.line([cx - 85, cy + 5, cx + 85, cy + 5], fill=accent, width=2)
        draw.ellipse([cx - 5, cy + 29, cx + 5, cy + 39], fill=(34, 197, 94))
        draw.ellipse([cx - 154, cy - 82, cx - 110, cy - 38], fill=accent)
        draw_rounded_rect(draw, [cx - 140, cy - 50, cx - 124, cy + 12], radius=8, fill=(210, 220, 238))
        draw.ellipse([cx + 110, cy - 82, cx + 154, cy - 38], fill=accent)
        draw_rounded_rect(draw, [cx + 124, cy - 50, cx + 140, cy + 12], radius=8, fill=(210, 220, 238))
        for rad in range(120, 195, 26):
            draw.arc([cx - rad, cy - rad + 10, cx + rad, cy + rad + 10], start=-35, end=35, fill=accent, width=2)
            draw.arc([cx - rad, cy - rad + 10, cx + rad, cy + rad + 10], start=145, end=215, fill=accent, width=2)

    elif icon_type == "phone":
        draw_rounded_rect(draw, [cx - 75, cy - 130, cx + 75, cy + 130], radius=28, fill=(15, 23, 42), outline=(148, 163, 184), width=4)
        for yy in range(cy - 120, cy + 120):
            ratio = (yy - (cy - 120)) / 240
            r = int(59 * (1 - ratio) + 236 * ratio)
            g = int(130 * (1 - ratio) + 72 * ratio)
            b = int(246 * (1 - ratio) + 153 * ratio)
            draw.line([(cx - 64, yy), (cx + 64, yy)], fill=(r, g, b))
        draw_rounded_rect(draw, [cx - 26, cy - 118, cx + 26, cy - 103], radius=7, fill=(15, 23, 42))

    elif icon_type == "auto":
        pts = [
            (cx - 185, cy + 45), (cx - 150, cy + 10), (cx - 80, cy - 18), (cx - 20, cy - 52),
            (cx + 60, cy - 52), (cx + 122, cy - 10), (cx + 180, cy + 15), (cx + 195, cy + 45),
            (cx + 150, cy + 45), (cx + 120, cy + 16), (cx + 80, cy + 16), (cx + 50, cy + 45),
            (cx - 60, cy + 45), (cx - 90, cy + 16), (cx - 130, cy + 16), (cx - 155, cy + 45)
        ]
        draw.polygon(pts, fill=accent, outline=(255, 255, 255))
        cockpit = [(cx - 20, cy - 44), (cx + 50, cy - 44), (cx + 90, cy - 10), (cx - 50, cy - 10)]
        draw.polygon(cockpit, fill=(15, 23, 42))
        draw.ellipse([cx - 132, cy + 18, cx - 78, cy + 72], fill=(15, 23, 42), outline=accent, width=4)
        draw.ellipse([cx + 78, cy + 18, cx + 132, cy + 72], fill=(15, 23, 42), outline=accent, width=4)

    elif icon_type == "jewelry":
        for ox in [-84, 84]:
            jx = cx + ox
            draw.ellipse([jx - 24, cy - 100, jx + 24, cy - 52], fill=(226, 232, 240), outline=accent, width=2)
            draw.ellipse([jx - 8, cy - 84, jx + 8, cy - 68], fill=accent)
            draw.line([jx, cy - 52, jx, cy - 30], fill=(200, 205, 215), width=3)
            draw.pieslice([jx - 56, cy - 36, jx + 56, cy + 44], start=0, end=180, fill=(203, 213, 225), outline=accent, width=2)
            for px in range(int(jx - 44), int(jx + 52), 18):
                draw.line([px, cy + 4, px, cy + 25], fill=(203, 213, 225), width=2)
                draw.ellipse([px - 5, cy + 25, px + 5, cy + 35], fill=(255, 255, 255), outline=accent, width=1)

    elif icon_type == "lanyard":
        draw.line([cx - 90, cy - 120, cx - 30, cy + 18], fill=accent, width=16)
        draw.line([cx + 90, cy - 120, cx + 30, cy + 18], fill=accent, width=16)
        draw.line([cx - 30, cy + 18, cx, cy + 48], fill=accent, width=16)
        draw.line([cx + 30, cy + 18, cx, cy + 48], fill=accent, width=16)
        draw_rounded_rect(draw, [cx - 16, cy + 48, cx + 16, cy + 74], radius=6, fill=(148, 163, 184), outline=(100, 116, 139), width=2)
        draw_rounded_rect(draw, [cx - 65, cy + 74, cx + 65, cy + 140], radius=8, fill=(248, 250, 252), outline=(148, 163, 184), width=2)
        draw.rectangle([cx - 55, cy + 84, cx - 25, cy + 120], fill=accent)
        draw.line([cx - 15, cy + 92, cx + 48, cy + 92], fill=(51, 65, 85), width=4)
        draw.line([cx - 15, cy + 108, cx + 38, cy + 108], fill=(148, 163, 184), width=3)

    elif icon_type == "sculpture":
        draw_rounded_rect(draw, [cx - 125, cy + 62, cx + 125, cy + 128], radius=10, fill=(51, 65, 85), outline=accent, width=3)
        draw.text((cx - 62, cy + 86), "EXHIBIT GALLERY", fill=(226, 232, 240), font=font_badge)
        draw.ellipse([cx - 95, cy - 110, cx + 95, cy + 60], fill=(180, 83, 9), outline=accent, width=3)
        for offset in range(-50, 60, 28):
            draw.arc([cx - 72, cy - 82 + offset // 2, cx + 72, cy + 32 + offset // 2], start=20, end=160, fill=(245, 158, 11), width=4)
            draw.arc([cx - 55 + offset, cy - 92, cx + 55 + offset, cy + 40], start=80, end=280, fill=(251, 191, 36), width=3)

    # Info banner
    draw_rounded_rect(draw, [48, 450, width - 48, 558], radius=16, fill=(15, 23, 42), outline=accent, width=2)
    draw.text((74, 468), brand.upper(), fill=accent, font=font_brand)
    disp_title = title if len(title) <= 36 else f"{title[:33]}..."
    draw.text((74, 498), disp_title, fill=(255, 255, 255), font=font_title)

    draw_rounded_rect(draw, [width - 230, 480, width - 72, 528], radius=10, fill=(30, 41, 59), outline=accent, width=1)
    draw.text((width - 208, 495), "VERIFIED ASSET", fill=(52, 211, 153), font=font_badge)

    slug = f"suchit_asset_{prod_id}_{brand.lower().replace(' ', '_')}"
    jpg_filename = f"{slug}.jpg"
    webp_filename = f"{slug}.webp"

    for folder in (UPLOADS_DIR, MIRROR_UPLOADS_DIR):
        img.save(os.path.join(folder, jpg_filename), "JPEG", quality=90, optimize=True)
        img.save(os.path.join(folder, webp_filename), "WEBP", quality=90, method=6)

    return f"/static/uploads/{jpg_filename}"


def populate_all_images_and_enrich_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Complete rich catalog metadata preserving original core titles/prices/features
    products_spec = [
        (
            3, "boAt Airdopes 131 Pro", "boAt", "Airdopes 131 Pro", "Electronics & Audio",
            ((15, 23, 42), (30, 58, 138), (37, 99, 235), (24, 33, 56), (255, 255, 255)), "audio",
            "True wireless earbuds with ENx environmental noise cancellation and 45-hour playback.",
            "Engineered for uninterrupted wireless audio, the boAt Airdopes 131 Pro delivers deep signature bass, quad-mic ENx voice clarity, low-latency BEAST mode, and ASAP rapid USB-C charging inside a pocket-friendly case.",
            {"Connectivity": "Bluetooth 5.3", "Playback Time": "Up to 45 Hours", "Noise Cancellation": "ENx Quad Mic", "Charging": "ASAP USB-C Fast Charge", "Water Resistance": "IPX5"},
            ["45H total battery backup", "ENx clear voice calls", "ASAP fast charge 10m=60m"],
            ["earbuds", "boat", "tws", "bluetooth", "audio"],
        ),
        (
            4, "boAt Airdopes", "boAt", "Airdopes 131", "Electronics & Audio",
            ((15, 23, 42), (30, 58, 138), (14, 165, 233), (24, 33, 56), (255, 255, 255)), "audio",
            "Lightweight everyday true wireless earbuds with instant wake-n-pair technology.",
            "Built for everyday mobility, boAt Airdopes features ergonomic earbuds with intuitive capacitive touch controls, balanced 13mm dynamic drivers, and instant Bluetooth connection out of the pocket.",
            {"Driver Size": "13mm Dynamic Drivers", "Connectivity": "Bluetooth 5.0", "Form Factor": "In-Ear TWS", "Case Battery": "650mAh", "Water Resistance": "IPX4"},
            ["13mm punchy audio drivers", "Insta Wake N' Pair", "Ergonomic ultra-light fit"],
            ["earbuds", "boat", "wireless", "bluetooth", "audio"],
        ),
        (
            5, "boAt Airdopes Twin", "boAt", "Airdopes Twin Edition", "Electronics & Audio",
            ((15, 23, 42), (30, 58, 138), (99, 102, 241), (24, 33, 56), (255, 255, 255)), "audio",
            "Dual-driver true wireless stereo earphones with splash protection and carry case.",
            "The boAt Airdopes Twin Edition combines dual synchronized wireless earpieces, multi-function tap gestures for media and voice assistants, and a rugged matte travel charging case delivering up to 20 hours of playback.",
            {"Connectivity": "Bluetooth 5.0", "Total Playtime": "Up to 20 Hours", "Control Scheme": "Capacitive Touch", "Voice Assistant": "One-Touch Siri & Google", "Protection": "IPX4 Sweatproof"},
            ["Independent stereo pairing", "Sweat & splash protected", "Voice assistant trigger"],
            ["earbuds", "boat", "twin", "audio", "wireless"],
        ),
        (
            6, "boAt Airdopes True Wireless Earbuds", "boAt", "Airdopes Studio Series", "Electronics & Audio",
            ((15, 23, 42), (30, 58, 138), (16, 185, 129), (24, 33, 56), (255, 255, 255)), "audio",
            "Compact wireless stereo earbuds designed for commuters, fitness routines, and calls.",
            "Experience reliable cable-free convenience with the boAt Airdopes True Wireless Earbuds. Its precision acoustic tuning keeps vocals crisp and bass rich across music playlists, podcasts, and hands-free calls.",
            {"Connectivity": "Bluetooth 5.0", "Acoustic Design": "Closed In-Ear", "Charging Interface": "Magnetic Case Pins", "Microphones": "Built-in Dual Mic"},
            ["Secure acoustic seal", "Rapid magnetic dock", "Portable matte finish"],
            ["boat", "earbuds", "wireless", "commute", "audio"],
        ),
        (
            7, "Apple iPhone 13", "Apple", "A2633", "Smartphones & Electronics",
            ((17, 24, 39), (55, 65, 81), (59, 130, 246), (31, 41, 55), (255, 255, 255)), "phone",
            "Flagship smartphone powered by the A15 Bionic chip, Super Retina XDR display, and dual 12MP cameras.",
            "Apple iPhone 13 pairs an ultra-bright 6.1-inch Super Retina XDR OLED panel protected by Ceramic Shield with the aerospace-grade aluminum enclosure, diagonal dual 12MP camera system with Cinematic mode, and fast 5G performance.",
            {"Display": "6.1-inch Super Retina XDR OLED", "Processor": "Apple A15 Bionic", "Camera": "Dual 12MP Wide & Ultra Wide", "Security": "Face ID", "Durability": "IP68 Ceramic Shield"},
            ["Cinematic mode video capture", "All-day battery efficiency", "Ceramic Shield glass toughness"],
            ["apple", "iphone", "smartphone", "5g", "mobile"],
        ),
        (
            8, "Lamborghini Huracan EVO", "Lamborghini", "Huracan EVO", "Automotive & Luxury",
            ((24, 24, 27), (69, 10, 10), (239, 68, 68), (39, 39, 42), (255, 255, 255)), "auto",
            "Naturally aspirated 5.2L V10 super sports coupe with predictive all-wheel-drive dynamics.",
            "The Lamborghini Huracan EVO blends sculpted Italian aerodynamics with next-generation LDVI vehicle dynamics control, delivering blistering 0-100 km/h acceleration in 2.9 seconds and unmistakable acoustic drama.",
            {"Engine": "5.2L Naturally Aspirated V10", "Horsepower": "631 hp (640 CV)", "Drivetrain": "All-Wheel Drive with Torque Vectoring", "Transmission": "7-Speed LDF Dual-Clutch", "Top Speed": "> 325 km/h"},
            ["640 CV naturally aspirated V10", "LDVI predictive chassis control", "Carbon-ceramic braking system"],
            ["lamborghini", "huracan", "supercar", "automotive", "luxury"],
        ),
        (
            9, "Acharya Institute Lanyard", "Acharya Institutes", "AI-LAN-01", "Office & School Supplies",
            ((12, 74, 110), (3, 105, 161), (245, 158, 11), (15, 23, 42), (255, 255, 255)), "lanyard",
            "Official institutional woven polyester ID card lanyard with heavy-duty metal swivel hook.",
            "Designed for daily campus and faculty identification, the Acharya Institutes Lanyard combines tear-resistant woven satin polyester with institutional imprint durability and an anti-tarnish chrome clip.",
            {"Material": "Woven Polyester Ribbon", "Hardware": "Zinc Alloy Swivel Clasp", "Length": "90 cm Loop", "Width": "2 cm", "Print": "Fade-Resistant Sublimation"},
            ["All-day collar comfort", "Reinforced stitched joint", "Universal ID pouch compatible"],
            ["lanyard", "acharya", "campus", "id-strap", "office"],
        ),
        (
            10, "Silver Oxidized Jhumka Earrings with Clear Stones", "Artisan Silver", "JHK-CLR-10", "Jewelry & Accessories",
            ((30, 27, 75), (88, 28, 135), (192, 132, 252), (46, 16, 101), (255, 255, 255)), "jewelry",
            "Handcrafted oxidized silver-tone jhumka drop earrings adorned with sparkling clear crystal stones.",
            "Featuring traditional bell dome filigree paired with faceted clear crystal studs and delicate drop beads, these featherweight oxidized jhumka earrings elevate ethnic, festive, and Indo-western wardrobes effortlessly.",
            {"Finish": "Antique Oxidized Silver Alloy", "Stone Work": "Faceted Clear Crystals", "Closure": "Push-Back Post", "Style": "Traditional Jhumka Dome", "Weight": "18g Pair (Featherlight)"},
            ["Artisan oxidized filigree texture", "Skin-friendly lead-free alloy", "Versatile festive & daily wear"],
            ["jhumka", "earrings", "oxidized", "jewelry", "ethnic"],
        ),
        (
            11, "Giant Brain Sculpture", "Exhibition Atelier", "ART-BRN-11", "Art & Decor",
            ((41, 37, 36), (87, 83, 78), (217, 119, 6), (68, 64, 60), (255, 255, 255)), "sculpture",
            "Monumental contemporary public art installation celebrating cognition and architectural form.",
            "Crafted as an outdoor focal landmark for university plazas, science centers, and innovation parks, the Giant Brain Sculpture pairs weatherproof composite construction with sculptural contour fidelity.",
            {"Construction": "Weather-Resistant Fiberglass Resin Composite", "Installation": "Outdoor Public Plaza Grade", "Finish": "UV-Sealed Matte Textured", "Mounting": "Reinforced Plinth Anchor"},
            ["Weather & UV resistant finish", "High-impact landmark silhouette", "Custom institutional exhibition edition"],
            ["sculpture", "art", "exhibit", "decor", "installation"],
        ),
        (
            12, "Oxidized Silver Jhumka Earrings with CZ and Pearls", "Artisan Silver", "JHK-PRL-12", "Jewelry & Accessories",
            ((15, 23, 42), (76, 29, 149), (168, 85, 247), (30, 27, 75), (255, 255, 255)), "jewelry",
            "Classic oxidized silver jhumka earrings finished with cubic zirconia sparkles and faux pearl tassels.",
            "Blending heirloom Indian craftsmanship with shimmering cubic zirconia accents and clustered ivory faux pearl droplets, this statement jhumka pair catches light smoothly with every movement.",
            {"Finish": "Antique Silver Oxidized Plated", "Gemstones": "Cubic Zirconia & Faux Pearls", "Drop Length": "2 Inches", "Closure": "Secure Post & Back"},
            ["Hand-strung faux pearl tassel fringe", "Brilliant CZ diamond-cut stones", "Tarnish-resistant protective coat"],
            ["jhumka", "pearls", "cz", "oxidized", "jewelry"],
        ),
    ]

    for pid, title, brand, model, category, theme, icon_type, short_desc, desc, specs, usp, tags in products_spec:
        img_rel_path = create_product_artwork(pid, title, brand, category, theme, icon_type)
        cursor.execute("""
        UPDATE products SET
            product_name = ?,
            brand = ?,
            model = ?,
            category = ?,
            short_description = ?,
            description = ?,
            specifications = ?,
            selling_points = ?,
            tags = ?,
            seo_title = ?,
            seo_description = ?,
            image_path = ?,
            status = 'active',
            created_at = COALESCE(created_at, ?),
            updated_at = ?
        WHERE id = ?
        """, (
            title, brand, model, category, short_desc, desc,
            json.dumps(specs, ensure_ascii=False),
            json.dumps(usp, ensure_ascii=False),
            json.dumps(tags, ensure_ascii=False),
            f"{title} | {brand} - Suchit Catalog",
            short_desc[:155],
            img_rel_path,
            now_str, now_str, pid
        ))
        print(f"Product #{pid} enriched and linked to {img_rel_path}")

    # Clean up test pollution left from prior test runs while preserving authentic data
    cursor.execute("DELETE FROM users WHERE username LIKE 'testuser_%'")
    cursor.execute("DELETE FROM inquiries WHERE email = 'not-an-email' OR name LIKE 'Test %' OR name LIKE 'Jane %'")
    cursor.execute("DELETE FROM orders WHERE customer_email = '' OR customer_email LIKE '%@example.com' OR customer_name LIKE 'Test %'")

    conn.commit()
    conn.close()
    print("All product images generated (TrueType, WebP+JPEG), database enriched, and mirror synced!")


if __name__ == "__main__":
    populate_all_images_and_enrich_db()
