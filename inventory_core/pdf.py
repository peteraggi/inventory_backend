"""
inventory_core/pdf.py — shared HTML-to-PDF rendering for document reports
(purchase orders, sale orders, invoices, ...), mirroring Odoo's QWeb PDF
reports: render a Django template to HTML, then rasterize to PDF.
"""
from io import BytesIO

from django.http import HttpResponse
from django.template.loader import render_to_string
from xhtml2pdf import pisa


def render_pdf(template_name: str, context: dict, filename: str) -> HttpResponse:
    html = render_to_string(template_name, context)
    buffer = BytesIO()
    result = pisa.CreatePDF(src=html, dest=buffer)
    if result.err:
        raise ValueError("Failed to render PDF")
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
