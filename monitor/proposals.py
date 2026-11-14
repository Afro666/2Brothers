"""Apply Context recall evidence to the Buyer/engine proposal flow."""
import hashlib

from agent.substitutes import AllergenPolicy
from monitor.recalls import audit, scan
from store import recalls
from store.buyer_context import excluded_allergens, product
from store.orders import get_offer


def apply_notices(gateway, kitchen_id, notices, *, live_enrichment=False):
    db, now = gateway.db, gateway.now()
    kitchen, proposals = recalls.context(db, kitchen_id)
    alerts = scan(notices, kitchen, now)
    audit(db, alerts, now)
    # Publish all holds before quoting any replacement.
    alerts = [recalls.remember(db, alert) for alert in alerts]
    alerts = [alert for alert in alerts if alert.get('status') != 'dismissed']
    results = []
    for proposal in proposals:
        offer = get_offer(db, proposal['offer_id'])
        ids = {line['product_id'] for line in offer['simulation']['lines']}
        relevant = [a for a in alerts if a['product_id'] in ids]
        held = False
        for alert in relevant:
            held = recalls.hold(db, kitchen_id, proposal['_id'], alert) or held
        if not held:
            continue
        if proposal['status'] != 'BLOCKED_BY_RECALL':
            gateway._audit(kitchen_id, 'recall_proposal_blocked', 'recall-monitor',
                           proposal_id=proposal['_id'], product_ids=sorted(ids & recalls.blocked_ids(db, kitchen_id)))
        if proposal.get('replacement_proposal_id'):
            results.append(gateway.get_proposal(kitchen_id, proposal['_id']))
            continue
        exclusions = excluded_allergens(db, kitchen_id)
        if exclusions is None:
            recalls.link(db, kitchen_id, proposal['_id'], recall_replan_error='KITCHEN_POLICY_UNKNOWN')
            continue
        policy, blocked = AllergenPolicy(tuple(exclusions)), recalls.blocked_ids(db, kitchen_id)
        swaps = {}
        for pid in sorted(ids & blocked):
            source = product(db, kitchen_id, pid)
            if not source or not source.get('brand'):
                continue
            for candidate in recalls.candidates(db, kitchen_id, source):
                if (candidate['product_id'] not in blocked and candidate.get('brand') and
                    candidate['brand'].casefold() != source['brand'].casefold() and
                    policy.allowed(candidate, substitute=True)):
                    swaps.setdefault(pid, []).append(candidate['product_id'])
        replacements = [c for pid in sorted(swaps) for c in swaps[pid]]
        safe_original = [pid for pid in proposal['request']['product_ids'] if pid not in blocked and
                         policy.allowed(product(db, kitchen_id, pid), substitute=True)]
        basket = list(dict.fromkeys([*safe_original, *replacements]))[:20]
        needs = _needs(proposal['request'], ids, swaps, lambda pid: pid not in blocked and
                       policy.allowed(product(db, kitchen_id, pid), substitute=True))
        if needs is not None:
            basket = [n['product_id'] for n in needs]
        if not basket:
            recalls.link(db, kitchen_id, proposal['_id'], recall_replan_error='NO_SAFE_REPLACEMENT')
            continue
        key = hashlib.sha256((proposal['_id'] + '|' + '|'.join(sorted(a['event_id'] for a in relevant))).encode()).hexdigest()
        try:
            # Provenance is the actor and the audit entry; the gateway sets made_by itself.
            request = {k: v for k, v in proposal['request'].items()
                       if k not in ('made_by', 'query', 'needs', 'items')}
            if needs is not None:
                request.update(quantity=str(len(needs)), unit='products')
            replacement = gateway.create_proposal(kitchen_id, {**request,
                'product_ids': basket, 'idempotency_key': 'recall-' + key}, 'recall-buyer', needs=needs)
            if (not replacement['lines'] or replacement.get('shortfall') not in ('0', '0.0', '0.00')
                    or replacement.get('shortfalls')):
                recalls.link(db, kitchen_id, proposal['_id'], recall_replan_error='REPLACEMENT_SHORTFALL')
                if recalls.reject_replacement(db, kitchen_id, replacement['proposal_id'],
                                              'recall replacement shortfall'):
                    gateway._audit(kitchen_id, 'recall_replacement_rejected', 'recall-monitor',
                                   proposal_id=proposal['_id'], replacement_proposal_id=replacement['proposal_id'],
                                   reason='REPLACEMENT_SHORTFALL')
                continue
            recalls.link(db, kitchen_id, proposal['_id'], replacement_proposal_id=replacement['proposal_id'],
                         recall_replan_error=None)
            from monitor.enrichment import attach
            try:
                attach(gateway, kitchen_id, replacement, live=live_enrichment)
            except (ValueError, RuntimeError, OSError):
                gateway._audit(kitchen_id, 'replacement_enrichment_unknown', 'recall-monitor',
                               proposal_id=replacement['proposal_id'])
            gateway._audit(kitchen_id, 'recall_replacement_proposed', 'recall-buyer',
                proposal_id=proposal['_id'], replacement_proposal_id=replacement['proposal_id'],
                expected_total=replacement['expected_total'], requires_human_approval=True)
        except Exception:
            # Upstream failure never clears the original hold or leaks credentials.
            recalls.link(db, kitchen_id, proposal['_id'], recall_replan_error='REPLACEMENT_UNAVAILABLE')
        results.append(gateway.get_proposal(kitchen_id, proposal['_id']))
    return results


def _needs(request, priced, swaps, safe):
    """#1482: a menu-plan (`needs`) or list (`items`, #1375) proposal is rebuilt line by line,
    each with its own quantity and unit; a recalled product is swapped for a safe one.
    None for a single-product request. [] when a line has no safe product (nothing proposed)."""
    if request.get('needs'):
        rows = [(n, [n['product_id']]) for n in request['needs']]
    elif request.get('items'):
        rows = [(item, [p for p in item.get('product_ids') or [] if p in priced] or item.get('product_ids') or [])
                for item in request['items'] if item.get('result', 'proposed') == 'proposed']
    else:
        return None
    out = []
    for row, pids in rows:
        keep = next((p for p in pids if safe(p)), None)
        if keep is not None:
            need = {k: row[k] for k in ('quantity', 'unit', 'stock_counted', 'sales_unit', 'set_by') if k in row}
            out.append({**need, 'product_id': keep})
            continue
        swap = next((s for p in pids for s in swaps.get(p, [])), None)
        if swap is None:
            return []
        # The swap's own sales unit may differ: keep the need in the line's measure.
        need = {k: row[k] for k in ('quantity', 'unit', 'stock_counted') if k in row}
        out.append({**need, 'product_id': swap})
    return out


def main():
    import argparse
    import json
    from pathlib import Path
    from gateway.service import Gateway
    from gateway.valio_client import ValioClient
    from store.db import get_db
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--kitchen-id', required=True)
    parser.add_argument('--live-enrichment', action='store_true', help='Use Context credits for manufacturer evidence')
    args = parser.parse_args()
    rows = apply_notices(Gateway(get_db(), ValioClient()), args.kitchen_id,
                         json.loads(args.fixture.read_text(encoding='utf-8'))['notices'], live_enrichment=args.live_enrichment)
    print(json.dumps(rows, default=str, ensure_ascii=False))


if __name__ == '__main__':
    main()
