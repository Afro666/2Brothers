"""Read-only selection evidence from the exact offers used for a quote."""
from decimal import Decimal

from engine.packs import to_sales_units


def selection_facts(offers, need: Decimal, measure: str) -> dict:
    if need <= 0:
        raise ValueError('need must be positive')
    def text(value):
        return format(value.quantize(Decimal('0.000001')).normalize(), 'f')
    out = {}
    for offer in offers:
        if offer.pack.measure != measure or offer.pack.size <= 0:
            raise ValueError('unproven selection measure')
        amount = None if offer.available is None else max(Decimal(0), offer.available) * offer.pack.size
        units, _ = to_sales_units(need, offer.pack)
        out[offer.product_id] = {
            'stock_state': 'unknown' if amount is None else 'confirmed' if amount > 0 else 'none',
            'stock_quantity_base': None if amount is None else text(amount),
            'stock_covers': None if amount is None else text(min(Decimal(1), amount / need)),
            'price_per_base_unit': text(offer.price_per_measure), 'base_unit': measure,
            'price_basis': 'ex_vat_before_basket_discounts',
            'base_per_sales_unit': text(offer.pack.size),
            'packs_needed': text(units), 'sales_unit': offer.pack.sales_unit,
            'first_arrival': offer.available_date.isoformat() if offer.available_date else None,
            'cutoff_passed': offer.cutoff_passed}
    return out
