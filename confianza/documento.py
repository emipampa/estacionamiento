"""Generación de un PDF de ejemplo con número de documento y QR de verificación.

En el producto real el PDF lo trae el usuario; acá sólo se usa para la demo y
para la función `agregar_qr`, que estampa el QR sobre un PDF existente.
"""
import io

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import config


def imagen_qr(url: str) -> ImageReader:
    qr = qrcode.QRCode(box_size=6, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def pdf_ejemplo(doc_id: str, titulo: str, cuerpo: str, firmante: str) -> bytes:
    """Arma un documento A4 con encabezado, cuerpo, pie con ID y QR."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    ancho, alto = A4
    url = f"{config.BASE_URL}/verificar/{doc_id}"

    c.setFont("Helvetica-Bold", 16)
    c.drawString(25 * mm, alto - 30 * mm, titulo)
    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, alto - 37 * mm, f"Documento N° {doc_id}")

    c.setFont("Helvetica", 11)
    y = alto - 55 * mm
    for linea in cuerpo.splitlines():
        c.drawString(25 * mm, y, linea)
        y -= 6 * mm

    c.drawString(25 * mm, y - 10 * mm, f"Firmante: {firmante}")

    # Pie: QR y leyenda de verificación
    c.drawImage(imagen_qr(url), 25 * mm, 20 * mm, 28 * mm, 28 * mm)
    c.setFont("Helvetica", 8)
    c.drawString(56 * mm, 40 * mm, f"Validado por {config.NOMBRE_PLATAFORMA}")
    c.drawString(56 * mm, 35 * mm, "Verificá este documento en:")
    c.drawString(56 * mm, 30 * mm, url)
    c.drawString(56 * mm, 25 * mm, "La firma digital se ve en el panel de firmas de Acrobat o con pyHanko.")

    c.showPage()
    c.save()
    return buf.getvalue()
