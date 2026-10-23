import base64
from html import escape
from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


def pdf_document(title, school, headings, rows, *, identity=(), status="", filename="finance.pdf"):
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 12
    styles["Title"].textColor = colors.HexColor("#234638")

    def text(value, style="BodyText"):
        return Paragraph(escape(str(value)), styles[style])

    elements = []
    if school.get("logo"):
        elements.append(
            Image(
                BytesIO(base64.b64decode(school["logo"])),
                width=18 * mm,
                height=18 * mm,
                kind="proportional",
            )
        )
    elements.extend(
        [
            text(school.get("name", "SchoolOS"), "Title"),
            text(school.get("address", "")),
            text(f"{school.get('phone', '')} / {school.get('email', '')}"),
            Spacer(1, 5 * mm),
            text(title, "Heading1"),
        ]
    )
    if status:
        elements.append(text(status, "Heading2"))
    for key, value in identity:
        elements.append(text(f"{key}: {value}"))
    elements.append(Spacer(1, 5 * mm))
    table = LongTable(
        [[text(v) for v in headings]] + [[text(v) for v in row] for row in rows],
        colWidths=[176 * mm / len(headings)] * len(headings),
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6eee9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#234638")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    elements.extend(
        [
            table,
            Spacer(1, 6 * mm),
            text(
                "School finance prototype. Payments are manually recorded; no bank"
                " verification is claimed."
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(17 * mm, 12 * mm, f"{title} | Page {doc.page}")

    SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
        invariant=1,
    ).build(elements, onFirstPage=footer, onLaterPages=footer)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response
