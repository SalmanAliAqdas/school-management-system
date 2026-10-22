import csv
from html import escape
from io import BytesIO, StringIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from audit.services import record_event
from core.models import SchoolSettings

MAX_EXPORT_ROWS = 5000


def safe_csv(value):
    value = str(value) if value is not None else ""
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
        or value.startswith(("\t", "\r", "\n"))
        else value
    )


def export_response(actor, *, title, headers, rows, kind, period):
    if len(rows) > MAX_EXPORT_ROWS:
        from django.core.exceptions import ValidationError

        raise ValidationError(
            "Export at most 5,000 rows. Narrow the date range or choose a summary report."
        )
    if kind == "csv":
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows([[safe_csv(value) for value in row] for row in rows])
        response = HttpResponse(
            stream.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = 'attachment; filename="attendance-report.csv"'
    else:
        output = BytesIO()
        school = SchoolSettings.objects.first()
        styles = getSampleStyleSheet()
        document = SimpleDocTemplate(
            output,
            pagesize=(297 * mm, 210 * mm),
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=12 * mm,
            bottomMargin=15 * mm,
        )
        elements = []
        if school and school.logo:
            with school.logo.open("rb") as logo:
                elements.append(
                    Image(BytesIO(logo.read()), width=18 * mm, height=18 * mm, kind="proportional")
                )
        elements += [
            Paragraph(escape(school.name if school else "RumiWare SchoolOS"), styles["Title"]),
            Paragraph(escape(title), styles["Heading2"]),
            Paragraph(escape(period), styles["Normal"]),
        ]
        if school:
            elements.append(
                Paragraph(
                    escape(f"{school.address} · {school.phone} · {school.email}"), styles["Normal"]
                )
            )
        elements.append(Spacer(1, 5 * mm))
        table_rows = [
            [
                Paragraph(escape(str(value) if value is not None else "—"), styles["BodyText"])
                for value in row
            ]
            for row in [headers, *rows]
        ]
        table = LongTable(
            table_rows, repeatRows=1, colWidths=[267 * mm / len(headers)] * len(headers)
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceabc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#234638")),
                    ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#dfe4dd")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f6f8f3")],
                    ),
                ]
            )
        )
        elements.append(table)
        elements += [
            Spacer(1, 5 * mm),
            Paragraph(
                "Finalized working-day records only. Missing registers are not absences. "
                "Late credit and excused exclusions follow the saved policy.",
                styles["Normal"],
            ),
        ]

        def footer(canvas, doc):
            canvas.setFont("Helvetica", 8)
            canvas.drawString(15 * mm, 8 * mm, f"Authorized attendance report · Page {doc.page}")

        document.build(elements, onFirstPage=footer, onLaterPages=footer)
        response = HttpResponse(output.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="attendance-report.pdf"'
    response["Cache-Control"] = "private, no-store"
    record_event(f"attendance.export_{kind}", actor=actor, target=title)
    return response
