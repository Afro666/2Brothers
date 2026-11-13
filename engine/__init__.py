"""Purchasing engine: deterministic quantities, pack rounding, urgency and the "why".

Pure functions, no I/O. The model never invents a number; it reads these.
Patterns from Aron's production purchasing engine (docs/plan.md), no company data.
"""

from engine.params import KitchenParams
from engine.packs import PackInfo, pack_info, to_sales_units
from engine.demand import safety_stock, stockout_adjusted
from engine.quantity import Item, LinePlan, replenish
from engine.offers import Offer, RequestPlan, plan_request
from engine.urgency import Urgency, urgency

__all__ = [
    "Item", "KitchenParams", "LinePlan", "Offer", "PackInfo", "RequestPlan", "Urgency",
    "pack_info", "plan_request", "replenish", "safety_stock", "stockout_adjusted",
    "to_sales_units", "urgency",
]
