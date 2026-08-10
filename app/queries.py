"""Shared filtering / sorting for the reports and allocation-summary pages."""

from flask import request

from app.models import Allocation, Meter, Beneficiary, UtilityType
from app.fiscal import current_period

# Column keys the templates may sort on.
SORT_COLUMNS = {
    "beneficiary": Beneficiary.name,
    "position": Beneficiary.position,
    "utility": UtilityType.name,
    "number": Meter.number,
    "quarter": Allocation.quarter,
    "allocated": Allocation.amount,
}


def parse_filters():
    """Read the filter/sort query string. quarter=0 means 'all quarters'."""
    fy_year, fy_quarter = current_period()
    quarter = request.args.get("quarter", fy_quarter, type=int)
    return {
        "year": request.args.get("year", fy_year, type=int),
        "quarter": quarter if quarter in (1, 2, 3, 4) else 0,
        "utility_type_id": request.args.get("utility_type_id", type=int) or 0,
        "position": (request.args.get("position") or "").strip(),
        "name": (request.args.get("name") or "").strip(),
        "sort": request.args.get("sort", "beneficiary"),
        "direction": "desc" if request.args.get("direction") == "desc" else "asc",
    }


def allocation_query(filters):
    """Allocations for the period, narrowed by utility / position / name."""
    query = (
        Allocation.query.join(Meter, Allocation.meter_id == Meter.id)
        .join(Beneficiary, Meter.beneficiary_id == Beneficiary.id)
        .join(UtilityType, Meter.utility_type_id == UtilityType.id)
        .filter(Allocation.year == filters["year"])
    )
    if filters["quarter"]:
        query = query.filter(Allocation.quarter == filters["quarter"])
    if filters["utility_type_id"]:
        query = query.filter(Meter.utility_type_id == filters["utility_type_id"])
    if filters["position"]:
        query = query.filter(Beneficiary.position == filters["position"])
    if filters["name"]:
        query = query.filter(Beneficiary.name.ilike(f"%{filters['name']}%"))
    return query


def apply_sort(query, filters):
    column = SORT_COLUMNS.get(filters["sort"], Beneficiary.name)
    return query.order_by(column.desc() if filters["direction"] == "desc" else column.asc())


def matching_utility_types(filters):
    query = UtilityType.query
    if filters["utility_type_id"]:
        query = query.filter(UtilityType.id == filters["utility_type_id"])
    return query.order_by(UtilityType.name).all()


def matching_beneficiaries(filters):
    query = Beneficiary.query
    if filters["position"]:
        query = query.filter(Beneficiary.position == filters["position"])
    if filters["name"]:
        query = query.filter(Beneficiary.name.ilike(f"%{filters['name']}%"))
    return query.order_by(Beneficiary.name).all()


def period_label(filters):
    return (
        f"{filters['year']} Q{filters['quarter']}"
        if filters["quarter"]
        else f"{filters['year']} (all quarters)"
    )
