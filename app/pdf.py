"""Small reusable helper for rendering a titled data table to a PDF."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


def table_pdf(title, subtitle, meta_lines, headers, rows, right_align_from=None, bold_last_row=False):
    """Render a table to PDF bytes.

    right_align_from: column index from which cells are right-aligned (for money).
    bold_last_row:    emphasise a trailing totals row.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        title=title,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()

    story = [Paragraph(title, styles["Title"]), Paragraph(subtitle, styles["Heading2"])]
    for line in meta_lines:
        story.append(Paragraph(line, styles["Normal"]))
    story.append(Spacer(1, 8 * mm))

    table = Table([headers] + rows, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#212529")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#adb5bd")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if right_align_from is not None:
        style.append(("ALIGN", (right_align_from, 1), (-1, -1), "RIGHT"))
    if bold_last_row and rows:
        style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e9ecef")))

    table.setStyle(TableStyle(style))
    story.append(table)
    doc.build(story)

    buffer.seek(0)
    return buffer.getvalue()
