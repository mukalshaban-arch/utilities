"""Carry-forward budget ledger for Major-Account water/power meters.

Each such meter is a single running balance:

    pool(Q)        = balance carried in from earlier quarters + this quarter's allocation
    balance(Q)     = pool(Q) - this quarter's usage
    carried out    = balance(Q), which becomes the carry-in of the next quarter

The carry-in is never stored; it is always the cumulative (allocation - usage) of
every earlier period, so the figures cannot drift out of step. Deficits carry as
negative numbers, and the ledger rolls continuously across year boundaries.
"""

from sqlalchemy import func

from app.extensions import db
from app.models import Allocation, Usage


def _before(model, year, quarter):
    """Rows for periods strictly earlier than (year, quarter)."""
    return db.or_(
        model.year < year,
        db.and_(model.year == year, model.quarter < quarter),
    )


def _sum(model, meter_id, condition):
    return (
        db.session.query(func.coalesce(func.sum(model.amount), 0))
        .filter(model.meter_id == meter_id, condition)
        .scalar()
    )


def carry_in(meter_id, year, quarter):
    """Balance carried into (year, quarter): cumulative allocation - usage before it."""
    allocated = _sum(Allocation, meter_id, _before(Allocation, year, quarter))
    used = _sum(Usage, meter_id, _before(Usage, year, quarter))
    return allocated - used


def meter_ledger(meter_id, year, quarter):
    """The full ledger line for one meter in one quarter."""
    carried = carry_in(meter_id, year, quarter)
    allocation = _sum(Allocation, meter_id, db.and_(Allocation.year == year, Allocation.quarter == quarter))
    usage = _sum(Usage, meter_id, db.and_(Usage.year == year, Usage.quarter == quarter))
    pool = carried + allocation
    return {
        "carry_in": carried,
        "allocation": allocation,
        "pool": pool,
        "usage": usage,
        "balance": pool - usage,
    }
