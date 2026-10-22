import base64
from html import escape
from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from audit.services import record_event


def report_pdf(actor, result):
    data = result.data
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#234638")
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        invariant=1,
    )

    def text(value, style="BodyText"):
        return Paragraph(escape(str(value) if value is not None else "—"), styles[style])

    school = data["school"]
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
    elements += [
        text(school["name"], "Title"),
        text(school["address"]),
        text(f"{school['phone']} · {school['email']}"),
        Spacer(1, 5 * mm),
        text("ACADEMIC REPORT CARD", "Heading2"),
        text(f"{data['session']} · {data['year']} · Version {data['version']}"),
        Spacer(1, 4 * mm),
    ]
    identity = [
        [text("STUDENT"), text(data["student"])],
        [text("ADMISSION / ROLL"), text(f"{data['admission']} / {data['roll'] or '—'}")],
        [text("CLASS / SECTION"), text(f"{data['class']} · {data['section']}")],
    ]
    identity_table = Table(identity, colWidths=[45 * mm, 105 * mm])
    identity_table.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)])
    )
    if data.get("photo"):
        elements.append(
            Table(
                [
                    [
                        identity_table,
                        Image(
                            BytesIO(base64.b64decode(data["photo"])),
                            width=22 * mm,
                            height=25 * mm,
                            kind="proportional",
                        ),
                    ]
                ],
                colWidths=[150 * mm, 25 * mm],
            )
        )
    else:
        elements.append(identity_table)
    elements.append(Spacer(1, 5 * mm))
    if data["outcome"] == "withheld":
        elements += [
            text("RESULT WITHHELD", "Heading2"),
            text(
                "Contact the examination office. Restricted marks are not included in this report."
            ),
        ]
    else:
        rows = [[text(v) for v in ("SUBJECT", "MARKS", "MAXIMUM", "WEIGHTED %", "GRADE", "STATUS")]]
        for subject in data["subjects"]:
            rows.append(
                [
                    text(subject["subject"]),
                    text(subject["obtained"]),
                    text(subject["maximum"]),
                    text(subject["percentage"]),
                    text(subject["grade"]),
                    text(subject["outcome"].title()),
                ]
            )
        table = LongTable(
            rows, colWidths=[45 * mm, 23 * mm, 25 * mm, 30 * mm, 20 * mm, 33 * mm], repeatRows=1
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edda")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d4ddd3")),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ]
            )
        )
        elements += [
            table,
            Spacer(1, 4 * mm),
            text(
                f"Total {data['obtained'] or '—'} / {data['maximum'] or '—'}    "
                f"Overall {data['percentage'] or '—'}%    Grade {data['grade'] or '—'}",
                "Heading3",
            ),
            text(f"Outcome: {data['outcome'].title()}"),
            text(
                f"Promotion recommendation: {data['promotion'].replace('_', ' ')}; "
                "subject to authorized school review."
            ),
        ]
        if data.get("rank"):
            elements.append(text(f"Position in configured scope: {data['rank']}"))
        for subject in data["subjects"]:
            elements.append(text(subject["subject"] + " — assessment breakdown", "Heading4"))
            for component in subject["components"]:
                elements.append(
                    text(
                        f"{component['assessment']}: {component.get('marks') or '—'} / "
                        f"{component['maximum']} · {component['status']} · "
                        f"weight {component['weight']}%"
                    )
                )
                if component.get("remarks"):
                    elements.append(text(component["remarks"]))
        elements += [
            Spacer(1, 4 * mm),
            text("Teacher remarks", "Heading4"),
            text(data["teacher_remarks"] or "No general remarks recorded."),
            text("Principal remarks", "Heading4"),
            text(data["principal_remarks"] or "No principal remarks recorded."),
        ]
    elements += [
        Spacer(1, 5 * mm),
        text(f"Recorded approval: {data['approved_by'] or 'No named approval recorded'}"),
        text(f"Principal information: {school.get('principal_name') or 'Not configured'}"),
        text(f"Issue date: {data['issued_at'][:10]} · Issued by {data['issued_by']}"),
        text("System record of approval. No handwritten signature or official seal is implied."),
        text(
            f"Policy: {data['policy']['name']} · rounding: half up, "
            f"{data['policy']['decimal_places']} decimal places. "
            "Missing marks remain incomplete; exemptions follow the saved policy."
        ),
    ]

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#647568"))
        canvas.drawString(
            17 * mm, 10 * mm, f"RumiWare SchoolOS · Report {result.pk} · v{data['version']}"
        )
        canvas.drawRightString(193 * mm, 10 * mm, str(document.page))

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="academic-report-card.pdf"'
    response["Cache-Control"] = "private, no-store"
    record_event("exam.report_pdf", actor=actor, target=result.pk)
    return response
