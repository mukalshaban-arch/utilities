import csv
import io
from datetime import datetime

from flask import Blueprint, render_template, Response
from flask_login import login_required, current_user
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from app.extensions import db
from app.models import POSITIONS, UtilityType, log_activity
from app.queries import parse_filters, allocation_query, apply_sort, period_label

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


def log_export(fmt, filters):
    """Record that a report left the system, and for which period / utility filter."""
    utility = None
    if filters["utility_type_id"]:
        matched = UtilityType.query.get(filters["utility_type_id"])
        utility = matched.name if matched else None

    log_activity(
        current_user,
        f"Generated {fmt} report",
        quarter=filters["quarter"] or None,
        year=filters["year"],
        utility=utility,
    )
    db.session.commit()


def build_rows(filters):
    """One row per allocated meter number, filtered and sorted."""
    allocations = apply_sort(allocation_query(filters), filters).all()
    return [
        {
            "beneficiary": a.meter.beneficiary.label,
            "position": a.meter.beneficiary.position,
            "utility_type": a.meter.utility_type.name,
            "number": a.meter.number,
            "quarter": a.quarter,
            "year": a.year,
            "allocated": a.amount,
        }
        for a in allocations
    ]


@reports_bp.route("/quarterly")
@login_required
def quarterly():
    filters = parse_filters()
    rows = build_rows(filters)
    return render_template(
        "reports/quarterly.html",
        rows=rows,
        filters=filters,
        total=sum((row["allocated"] for row in rows), 0),
        period=period_label(filters),
        utility_types=UtilityType.query.order_by(UtilityType.name).all(),
        positions=POSITIONS,
    )


@reports_bp.route("/quarterly.csv")
@login_required
def quarterly_csv():
    filters = parse_filters()
    rows = build_rows(filters)
    log_export("CSV", filters)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Beneficiary", "Position", "Utility Type", "Number", "Quarter", "Allocated (UGX)"])
    for row in rows:
        writer.writerow(
            [
                row["beneficiary"],
                row["position"],
                row["utility_type"],
                row["number"],
                f"Q{row['quarter']} {row['year']}",
                row["allocated"],
            ]
        )

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={download_name(filters)}.csv"},
    )


def download_name(filters):
    quarter = f"Q{filters['quarter']}" if filters["quarter"] else "all-quarters"
    return f"allocations_{filters['year']}_{quarter}"


def active_filter_text(filters):
    """Human-readable line describing the filters, so the PDF is self-explanatory."""
    parts = []
    if filters["utility_type_id"]:
        utility = UtilityType.query.get(filters["utility_type_id"])
        if utility:
            parts.append(f"Utility: {utility.name}")
    if filters["position"]:
        parts.append(f"Position: {filters['position']}")
    if filters["name"]:
        parts.append(f"Name contains: '{filters['name']}'")
    return " | ".join(parts) if parts else "No filters applied"


def ugx(amount):
    return f"UGX {amount or 0:,.0f}"


@reports_bp.route("/quarterly.pdf")
@login_required
def quarterly_pdf():
    filters = parse_filters()
    rows = build_rows(filters)
    total = sum((row["allocated"] for row in rows), 0)
    log_export("PDF", filters)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        title=f"Allocations {period_label(filters)}",
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()

    story = [
        Paragraph("Utility Allocations", styles["Title"]),
        Paragraph(period_label(filters), styles["Heading2"]),
        Paragraph(active_filter_text(filters), styles["Normal"]),
        Paragraph(f"Generated {datetime.now().strftime('%d %b %Y %H:%M')}", styles["Normal"]),
        Spacer(1, 8 * mm),
    ]

    data = [["Beneficiary", "Position", "Utility", "Number", "Quarter", "Allocated"]]
    for row in rows:
        data.append(
            [
                row["beneficiary"],
                row["position"],
                row["utility_type"],
                row["number"],
                f"Q{row['quarter']} {row['year']}",
                ugx(row["allocated"]),
            ]
        )
    if rows:
        data.append(["Total", "", "", "", f"{len(rows)} allocation(s)", ugx(total)])
    else:
        data.append(["No allocations match these filters.", "", "", "", "", ""])

    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#212529")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e9ecef")),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#adb5bd")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fa")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    doc.build(story)

    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={download_name(filters)}.pdf"},
    )
