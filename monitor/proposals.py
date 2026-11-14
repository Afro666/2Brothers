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
        replacements = []
        for pid in sorted(ids & blocked):
            source = product(db, kitchen_id, pid)
            if not source or not source.get('brand'):
                continue
            for candidate in recalls.candidates(db, kitchen_id, source):
                if (candidate['product_id'] not in blocked and candidate.get('brand') and
                    candidate['brand'].casefold() != source['brand'].casefold() and
                    policy.allowed(candidate, substitute=True)):
                    replacements.append(candidate['product_id'])
        safe_original = [pid for pid in proposal['request']['product_ids'] if pid not in blocked and
                         policy.allowed(product(db, kitchen_id, pid), substitute=True)]
        basket = list(dict.fromkeys([*safe_original, *replacements]))[:20]
        if not basket:
            recalls.link(db, kitchen_id, proposal['_id'], recall_replan_error='NO_SAFE_REPLACEMENT')
            continue
        key = hashlib.sha256((proposal['_id'] + '|' + '|'.join(sorted(a['event_id'] for a in relevant))).encode()).hexdigest()
        try:
            # Provenance is the actor and the audit entry; the gateway sets made_by itself.
            request = {k: v for k, v in proposal['request'].items() if k not in ('made_by', 'query')}
            replacement = gateway.create_proposal(kitchen_id, {**request,
                'product_ids': basket, 'idempotency_key': 'recall-' + key}, 'recall-buyer')
            if not replacement['lines'] or replacement.get('shortfall') not in ('0', '0.0', '0.00'):
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
