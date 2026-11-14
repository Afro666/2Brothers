"""Deterministic chef choices from supplier links, then catalog search."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from store.allergen_groups import excluded_allergen_codes


@dataclass(frozen=True)
class AllergenPolicy:
    excluded: tuple[str, ...] = ()

    def __post_init__(self):
        # A group code (AW, AN) means its whole group; the shared rule is in store.allergen_groups.
        object.__setattr__(self, 'excluded', tuple(excluded_allergen_codes(self.excluded)))

    def allowed(self, product, *, substitute=False):
        if not isinstance(product, dict):
            return False
        allergens = product.get('allergens')
        if not isinstance(allergens, dict):
            return False
        levels = [allergens.get(key) for key in ('contains', 'may_contain', 'undeclared')]
        if any(not isinstance(level, list) or any(not isinstance(v, str) for v in level) for level in levels):
            return False
        if set(self.excluded).intersection(v for level in levels for v in level):
            return False
        # The requested product may remain visible as unknown in a kitchen with
        # no restrictions. A proposed substitute always needs known allergen data.
        return product.get('allergen_data_known') is True or (not self.excluded and not substitute)


def _amounts(lines):
    """Sum line quantities per unit, e.g. '698 ST' or '16 KI + 84 ST'."""
    totals = {}
    for line in lines:
        unit = line.get('unit') or ''
        try:
            qty = Decimal(str(line['quantity']))
        except (InvalidOperation, KeyError, TypeError):
            return None
        totals[unit] = totals.get(unit, Decimal(0)) + qty
    return ' + '.join(f'{qty.normalize():f} {unit}'.strip() for unit, qty in totals.items())


def _original_basket_reason(lines):
    """The Buyer's own basket with some stock unconfirmed: say which part is which."""
    confirmed = [line for line in lines if line.get('unknown_stock') is False]
    waiting = [line for line in lines if line.get('unknown_stock') is not False]
    have, wait = _amounts(confirmed), _amounts(waiting)
    if have is None or wait is None:
        return "The Buyer's basket as proposed; part of it waits for stock confirmation."
    if not confirmed:
        return f"The Buyer's basket as proposed: {wait} waits for stock confirmation."
    return f"The Buyer's basket as proposed: {have} confirmed, {wait} waits for stock confirmation."


class SubstitutePlanner:
    def __init__(self, lookup, policy):
        self.lookup, self.policy = lookup, policy

    async def plan(self, buyer, simulation, read):
        source_ids = buyer.offer_products[simulation['offer_id']]
        sources = [self.lookup(pid) for pid in source_ids]
        eligible_sources = [row for row in sources if row and self.policy.allowed(row)]
        source_ids = [row['product_id'] for row in eligible_sources]
        options, seen_baskets = [], set()

        def add(quote, source, candidate=None):
            lines = quote.get('lines', [])
            if quote.get('mandate', {}).get('verdict') != 'NEEDS_APPROVAL' or not lines:
                return
            basket = tuple((line['product_id'], line['quantity'], line.get('unit')) for line in lines)
            if basket in seen_baskets:
                return
            if any(not self.policy.allowed(self.lookup(line['product_id'])) for line in lines):
                return
            if candidate and candidate not in {line['product_id'] for line in lines}:
                return  # engine excluded it (e.g. cutoff passed or incompatible unit)
            seen_baskets.add(basket)
            tier = ('good', 'better', 'best')[len(options)]
            unknown = any(line.get('unknown_stock') is not False for line in lines)
            allergens_known = all(self.lookup(line['product_id']).get('allergen_data_known') is True for line in lines)
            if source == 'original' and unknown:
                reason = _original_basket_reason(lines)
            else:
                reason = ('Requested product, confirmed portion only.' if source == 'original'
                          else 'Supplier-linked substitute sized by the engine.' if source == 'supplier'
                          else 'Catalog alternative sized by the engine.')
            gap = [line for line in lines if 'SUBSTITUTE_NEEDS_OK' in (line.get('reason_codes') or [])]
            if gap:
                # S02 (#731): the engine filled the original's gap by weight or volume. The
                # gateway can do this on the first quote too (#1032), so it applies to every source.
                reason = (f"Requested product for what is in stock; the missing part filled with "
                          f"{_amounts(gap)} of the substitute, sized by weight or volume. A person says yes first.")
            if unknown and (gap or source != 'original'):
                reason += ' Supplier stock still needs confirmation.'
            if not allergens_known:
                reason += ' Allergen data is unknown; chef review required.'
            options.append({'tier': tier, 'source': source, 'offer_id': quote['offer_id'],
                            'expected_total': quote['expected_total'], 'currency': quote['currency'],
                            'lines': lines, 'why': reason, 'requires_chef_approval': True,
                            'allergen_data_known': allergens_known, 'stock_confirmed': not unknown})

        add(simulation, 'original')
        candidates = []
        for product in eligible_sources:
            for pid in product.get('substitutions', [])[:8]:
                if isinstance(pid, str) and pid not in source_ids and pid not in [row[0] for row in candidates]:
                    candidates.append((pid, 'supplier'))

        async def assess(pid, source):
            row = self.lookup(pid)
            if not row or not self.policy.allowed(row, substitute=True):
                return
            buyer.products.add(pid)  # trusted, kitchen-scoped host catalog lookup
            basket = [*source_ids, pid]
            offer = await read('get_offer', {'product_ids': basket, 'need_id': buyer.need_id,
                                           'requested_date': buyer.requested_date})
            quote = await read('simulate_order', {'offer_id': offer['offer_id']})
            add(quote, source, pid)

        for pid, source in candidates[:4]:
            if len(options) >= 3:
                break
            await assess(pid, source)
        if len(options) < 3 and eligible_sources:
            first = eligible_sources[0]
            filters = {'exclude_allergens': list(self.policy.excluded), 'allergen_strictness': 'strict'}
            if first.get('category'):
                filters['category'] = first['category']
            query = next(iter((first.get('names') or {}).values()), '')[:200]
            result = await read('search_products', {'query': query, 'filters': filters})
            tried = set(source_ids) | {pid for pid, _ in candidates}
            for row in result.get('products', [])[:4]:
                pid = row.get('product_id')
                if pid and pid not in tried and len(options) < 3:
                    tried.add(pid)
                    await assess(pid, 'catalog')
        return options
