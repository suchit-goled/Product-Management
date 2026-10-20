"""
Suchit Catalog - Professional PDF Generation Service
Generates beautifully typeset single-product sheets and multi-product catalog books
using ReportLab with custom typography, clean tables, images, and Suchit branding.
"""
import os
import io
import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether, PageBreak, HRFlowable
)
from reportlab.pdfgen import canvas
import logging

logger = logging.getLogger(__name__)

# Suchit Brand Color Palette
PRIMARY_COLOR = colors.HexColor("#1e3a8a")     # Deep Indigo / Navy
SECONDARY_COLOR = colors.HexColor("#2563eb")   # Bright Indigo
TEXT_DARK = colors.HexColor("#0f172a")         # Slate 900
TEXT_MUTED = colors.HexColor("#475569")        # Slate 600
BG_LIGHT = colors.HexColor("#f8fafc")          # Slate 50
ACCENT_GREEN = colors.HexColor("#059669")      # Emerald 600
BORDER_COLOR = colors.HexColor("#cbd5e1")      # Slate 300


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print 'Page X of Y' in the footer."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(TEXT_MUTED)
        
        # Top subtle rule and brand marker
        self.setStrokeColor(BORDER_COLOR)
        self.setLineWidth(0.5)
        self.line(40, letter[1] - 35, letter[0] - 40, letter[1] - 35)
        self.drawString(40, letter[1] - 30, "SUCHIT • AI PRODUCT CATALOG")
        date_str = datetime.datetime.now().strftime("%B %d, %Y")
        self.drawRightString(letter[0] - 40, letter[1] - 30, date_str)

        # Bottom footer
        self.line(40, 40, letter[0] - 40, 40)
        self.drawString(40, 28, "Suchit Intelligent Product Catalog Engine • All specifications subject to verification")
        page_text = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(letter[0] - 40, 28, page_text)
        self.restoreState()


def get_styles():
    base_styles = getSampleStyleSheet()
    styles = {}

    styles['Title'] = ParagraphStyle(
        'DocTitle',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=PRIMARY_COLOR,
        spaceAfter=4
    )

    styles['Subtitle'] = ParagraphStyle(
        'DocSubtitle',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=TEXT_MUTED,
        spaceAfter=12
    )

    styles['SectionHeading'] = ParagraphStyle(
        'SectionHeading',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=PRIMARY_COLOR,
        spaceBefore=10,
        spaceAfter=6
    )

    styles['Body'] = ParagraphStyle(
        'BodyText',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=TEXT_DARK,
        spaceAfter=6
    )

    styles['BodyMuted'] = ParagraphStyle(
        'BodyMuted',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=TEXT_MUTED
    )

    styles['Bullet'] = ParagraphStyle(
        'BulletText',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=TEXT_DARK,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3
    )

    styles['TableHeader'] = ParagraphStyle(
        'TableHeader',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white
    )

    styles['TableCell'] = ParagraphStyle(
        'TableCell',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=TEXT_DARK
    )

    styles['PriceBadge'] = ParagraphStyle(
        'PriceBadge',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=ACCENT_GREEN
    )

    return styles


def _build_product_story(product: dict, styles: dict, base_dir: str = None) -> list:
    """Builds flowable elements for a single product catalog sheet."""
    story = []

    pname = product.get("product_name") or "Unnamed Product"
    brand = product.get("brand") or "Unspecified Brand"
    category = product.get("category") or "General"
    price = product.get("price") or "N/A"
    dim = product.get("dimensions") or "N/A"
    short_desc = product.get("short_description") or ""
    desc = product.get("description") or ""
    features = product.get("features") or []
    specs = product.get("specifications") or {}
    usp = product.get("selling_points") or []
    tags = product.get("tags") or []
    img_path = product.get("image_path") or ""

    # Header block
    story.append(Spacer(1, 10))
    story.append(Paragraph(pname, styles['Title']))
    sub_text = f"<b>Brand:</b> {brand} &nbsp;|&nbsp; <b>Category:</b> {category} &nbsp;|&nbsp; <b>ID:</b> #{product.get('id', 'N/A')}"
    story.append(Paragraph(sub_text, styles['Subtitle']))
    story.append(HRFlowable(width="100%", thickness=1, color=SECONDARY_COLOR, spaceBefore=0, spaceAfter=10))

    # Two column overview: Left image (or placeholder), Right quick details
    image_flowable = None
    if img_path:
        # Resolve path
        candidate_paths = [
            img_path,
            os.path.join(base_dir or "", img_path.lstrip("/")),
            os.path.join(base_dir or "", "static", img_path.replace("/static/", "").lstrip("/")),
            os.path.join(base_dir or "", "my-project-folder", img_path.lstrip("/"))
        ]
        for p in candidate_paths:
            if os.path.exists(p) and os.path.isfile(p):
                try:
                    image_flowable = RLImage(p, width=2.4*inch, height=2.4*inch, kind='proportional')
                    break
                except Exception as e:
                    logger.debug(f"Failed to load image in PDF: {e}")

    if not image_flowable:
        # Placeholder box
        placeholder_table = Table(
            [[Paragraph("<font color='#64748b'>No Image Available</font>", styles['BodyMuted'])]],
            colWidths=[2.4*inch],
            rowHeights=[2.0*inch]
        )
        placeholder_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
            ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        image_flowable = placeholder_table

    # Right side meta details
    right_meta = [
        [Paragraph("<b>Price:</b>", styles['Body']), Paragraph(f"<b>{price}</b>", styles['PriceBadge'])],
        [Paragraph("<b>Dimensions:</b>", styles['Body']), Paragraph(dim, styles['Body'])],
        [Paragraph("<b>Status:</b>", styles['Body']), Paragraph(f"Active Catalog Item", styles['BodyMuted'])],
    ]
    if product.get('model'):
        right_meta.insert(1, [Paragraph("<b>Model:</b>", styles['Body']), Paragraph(str(product['model']), styles['Body'])])

    meta_table = Table(right_meta, colWidths=[1.1*inch, 3.2*inch])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))

    top_row = Table(
        [[image_flowable, meta_table]],
        colWidths=[2.6*inch, 4.4*inch]
    )
    top_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (1, 0), (1, 0), 12),
        ('RIGHTPADDING', (0, 0), (0, 0), 6),
    ]))
    story.append(top_row)
    story.append(Spacer(1, 10))

    # Short Description Callout Box
    if short_desc:
        callout_table = Table([[Paragraph(f"<i>{short_desc}</i>", styles['Body'])]], colWidths=[7.0*inch])
        callout_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
            ('BOX', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(callout_table)
        story.append(Spacer(1, 8))

    # Detailed Marketing Description
    if desc and desc != short_desc:
        story.append(Paragraph("Product Overview", styles['SectionHeading']))
        story.append(Paragraph(desc.replace("\n", "<br/>"), styles['Body']))
        story.append(Spacer(1, 6))

    # Key Features
    if features:
        story.append(Paragraph("Key Features & Capabilities", styles['SectionHeading']))
        for feat in features:
            story.append(Paragraph(f"• &nbsp; {feat}", styles['Bullet']))
        story.append(Spacer(1, 6))

    # Technical Specifications Table
    if specs and isinstance(specs, dict):
        story.append(Paragraph("Technical Specifications", styles['SectionHeading']))
        spec_rows = [[Paragraph("Attribute", styles['TableHeader']), Paragraph("Specification Details", styles['TableHeader'])]]
        
        for idx, (k, v) in enumerate(specs.items()):
            row_bg = colors.white if idx % 2 == 0 else BG_LIGHT
            spec_rows.append([
                Paragraph(f"<b>{k}</b>", styles['TableCell']),
                Paragraph(str(v), styles['TableCell'])
            ])

        spec_table = Table(spec_rows, colWidths=[2.2*inch, 4.8*inch])
        spec_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PRIMARY_COLOR),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(spec_table)
        story.append(Spacer(1, 8))

    # Commercial Selling Points
    if usp:
        story.append(Paragraph("Commercial Selling Highlights", styles['SectionHeading']))
        for point in usp:
            story.append(Paragraph(f"✓ &nbsp; <b>{point}</b>", styles['Bullet']))
        story.append(Spacer(1, 6))

    # Search Tags & SEO
    if tags:
        tag_str = ", ".join(tags)
        story.append(Paragraph(f"<b>Search & Catalog Keywords:</b> {tag_str}", styles['BodyMuted']))

    return story


def generate_single_product_pdf(product: dict, base_dir: str = None) -> bytes:
    """Generates PDF bytes for a single product catalog sheet."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=50
    )

    styles = get_styles()
    story = _build_product_story(product, styles, base_dir=base_dir)

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()


def generate_catalog_pdf(products: list, base_dir: str = None) -> bytes:
    """Generates a multi-page PDF catalog book for all provided products."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=50
    )

    styles = get_styles()
    story = []

    # Cover / Title Page
    story.append(Spacer(1, 40))
    story.append(Paragraph("SUCHIT", ParagraphStyle(
        'CoverBrand',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=36,
        leading=42,
        textColor=PRIMARY_COLOR,
        alignment=1
    )))
    story.append(Paragraph("INTELLIGENT PRODUCT CATALOG", ParagraphStyle(
        'CoverSub',
        parent=styles['Subtitle'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=20,
        textColor=SECONDARY_COLOR,
        alignment=1
    )))
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="60%", thickness=2, color=SECONDARY_COLOR, spaceBefore=0, spaceAfter=20, hAlign='CENTER'))
    
    date_str = datetime.datetime.now().strftime("%B %Y")
    cover_meta = f"Comprehensive Catalog Directory<br/>Generated: {date_str} &nbsp;|&nbsp; Total Records: {len(products)}"
    story.append(Paragraph(cover_meta, ParagraphStyle(
        'CoverMeta',
        parent=styles['BodyMuted'],
        fontSize=11,
        leading=16,
        alignment=1
    )))
    story.append(Spacer(1, 40))

    # Catalog Index Table on Cover Page
    if products:
        story.append(Paragraph("Catalog Index Summary", styles['SectionHeading']))
        summary_rows = [[
            Paragraph("ID", styles['TableHeader']),
            Paragraph("Product Name", styles['TableHeader']),
            Paragraph("Brand", styles['TableHeader']),
            Paragraph("Category", styles['TableHeader']),
            Paragraph("Price", styles['TableHeader'])
        ]]
        for idx, p in enumerate(products):
            pname = p.get('product_name', 'Unnamed')
            pbrand = p.get('brand', 'Unspecified')
            pcat = p.get('category', 'General')
            pprice = p.get('price', '-')
            pid = f"#{p.get('id', idx+1)}"
            summary_rows.append([
                Paragraph(pid, styles['TableCell']),
                Paragraph(f"<b>{pname}</b>", styles['TableCell']),
                Paragraph(pbrand, styles['TableCell']),
                Paragraph(pcat, styles['TableCell']),
                Paragraph(pprice, styles['TableCell'])
            ])

        sum_table = Table(summary_rows, colWidths=[0.6*inch, 2.5*inch, 1.4*inch, 1.5*inch, 1.0*inch])
        sum_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PRIMARY_COLOR),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(sum_table)

    story.append(PageBreak())

    # Individual Product Pages
    for idx, product in enumerate(products):
        product_story = _build_product_story(product, styles, base_dir=base_dir)
        story.extend(product_story)
        if idx < len(products) - 1:
            story.append(PageBreak())

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()
