"""Purchasing engine: deterministic quantities, pack rounding, urgency and the "why".

Pure functions, no I/O. The model never invents a number; it reads these.
Patterns from Aron's production purchasing engine (docs/plan.md), no company data.
"""

from engine.params import KitchenParams
from engine.packs import PackInfo, pack_info, to_sales_units
from engine.demand import safety_stock, stockout_adjusted
from engine.quantity import Item, LinePlan, replenish
from engine.offers import Offer, RequestPlan, plan_request
from engine.partial import FillPart, PartialFill, partial_fill
from engine.urgency import Urgency, urgency
from engine.allergens import allergen_codes, allergen_rule_hits
from engine.padding import Padding, Wanted, pad_to_free_delivery
from engine.addable import AddableRow, Candidate, Timing, rank_addable, rank_key

__all__ = [
    "Padding", "Wanted", "pad_to_free_delivery",
    "allergen_codes",
    "allergen_rule_hits",
    "AddableRow", "Candidate", "Timing", "rank_addable", "rank_key",
    "Item", "KitchenParams", "LinePlan", "Offer", "PackInfo", "RequestPlan", "Urgency",
    "pack_info", "plan_request", "replenish", "safety_stock", "stockout_adjusted",
    "to_sales_units", "urgency",
    "FillPart", "PartialFill", "partial_fill",
]
