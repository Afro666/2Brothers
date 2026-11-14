from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import mongomock
import pytest

from gateway.brief_facts import collect
from gateway.brief import checked_lines

NOW = datetime(2026, 11, 14, 9, tzinfo=timezone.utc)


@pytest.fixture
def source():
    db = mongomock.MongoClient(tz_aware=True).brief
    db.products.insert_one({'_id': 'milk', 'names': {'en': 'Milk', 'fi': 'Maito'}})
    db.suppliers.insert_one({'_id':'s','supplier_id':'s','kitchen_id':'k','name':'Supplier'})
    return db, SimpleNamespace(db=db, now=lambda: NOW)


def proposal(db, ident='p', *, closing=None, valid=None, total='12.00', kitchen='k'):
    db.offers.insert_one({'_id':ident+'-offer','kitchen_id':kitchen,
        'valid_until':valid or NOW+timedelta(hours=1),'requested_date':'2026-11-14',
        'simulation':{'expected_total':total,'lines':[{'product_id':'milk','quantity':'5',
        'unit':'L','closing_time':closing}],
        'blocks':[{'supplier_id':'s','name':'Supplier','expected_total':total}]}})
    db.proposals.insert_one({'_id':ident,'kitchen_id':kitchen,'status':'READY',
                             'offer_id':ident+'-offer'})


def test_supplier_cutoff_not_offer_expiry_and_local_urgency(source):
    db, gw = source
    tomorrow = NOW+timedelta(days=1)
    proposal(db,closing=tomorrow)
    morning = collect(gw,'k','morning','en')
    assert [r['kind'] for r in morning] == ['WAITING_DRAFTS']
    evening = collect(gw,'k','evening','fi')
    assert evening[0]['kind'] == 'CUTOFF' and not evening[0]['urgent']
    assert '2026-11-15' in evening[0]['variants'][0]
    proposal(db,'expired',closing=NOW,valid=NOW-timedelta(seconds=1))
    assert all(r['ref_id'] != 'expired' for r in collect(gw,'k','morning','en'))


@pytest.mark.parametrize('lang',['en','fi'])
def test_all_ranked_kinds_grounded_and_scope(source,lang):
    db,gw=source
    proposal(db,closing=NOW+timedelta(hours=2))
    proposal(db,'draft')
    proposal(db,'other',closing=NOW,kitchen='other')
    db.recall_alerts.insert_one({'_id':'recall','kitchen_id':'k','product_id':'milk','status':'active'})
    db.supplier_offers.insert_one({'_id':'suggestion','kitchen_id':'k','status':'OPEN',
                                  'supplier_id':'s','product_id':'milk','requested_date':'2026-11-14'})
    db.orders.insert_one({'_id':'order','kitchen_id':'k','status':'SENT','outcome':'SENT',
                          'offer_id':'p-offer','supplier_id':'s','supplier_must_confirm':['s']})
    rows=collect(gw,'k','morning',lang)
    assert [r['kind'] for r in rows]==['CUTOFF','RECALL','SUPPLIER_OFFER','DELIVERY','WAITING_DRAFTS','UNCONFIRMED']
    raw={'lines':[{'kind':r['kind'],'ref_id':r['ref_id'],'text':r['variants'][1],
                   'numbers':r['numbers']} for r in rows]}
    assert checked_lines(raw,rows,lang)[1]==len(rows)
    assert 'other' not in str(rows)
    db.recall_alerts.update_one({'_id':'recall'},{'$set':{'status':'dismissed'}})
    assert 'RECALL' not in [r['kind'] for r in collect(gw,'k','morning',lang)]


def test_delivery_check_uses_latest_counts_only(source):
    db,gw=source
    db.orders.insert_one({'_id':'order','kitchen_id':'k','status':'SENT','outcome':'SENT'})
    def audit(at,statuses):
        db.audit_log.insert_one({'server':{'kitchen_id':'k','at':at.isoformat()},
            'event':{'kind':'delivery_note_read','order_id':'order','statuses':statuses}})
    audit(NOW,{'SHORT':2,'SUBSTITUTE':1})
    rows=collect(gw,'k','evening','en')
    assert len(rows)==1 and rows[0]['kind']=='DELIVERY_CHECK'
    assert 'SHORT 2' in rows[0]['variants'][0] and 'SUBSTITUTE 1' in rows[0]['variants'][0]
    audit(NOW+timedelta(minutes=1),{'RECEIVED':3})
    assert collect(gw,'k','evening','en')==[]


def test_unknown_totals_are_not_zero_and_six_rows_maximum(source):
    db,gw=source
    proposal(db,total=None)
    rows=collect(gw,'k','morning','en')
    assert 'not fully known' in rows[0]['variants'][0] and 'EUR 0' not in rows[0]['variants'][0]
    for i in range(9):
        proposal(db,f'cutoff-{i}',closing=NOW+timedelta(minutes=i))
    assert len(collect(gw,'k','morning','en'))==6


@pytest.mark.parametrize('lang',['en','fi'])
def test_recalled_stock_with_unknown_count_is_reported(source,lang):
    from store.history import record_stock_count
    db,gw=source
    record_stock_count(db,'k',NOW,[{'product_id':'milk','unit':'L','on_hand':None}])
    db.recall_alerts.insert_one({'_id':'recall','kitchen_id':'k','product_id':'milk','status':'active'})
    rows=collect(gw,'k','morning',lang)
    assert len(rows)==1 and rows[0]['kind']=='RECALL' and rows[0]['numbers']==[]
    assert checked_lines({'lines':[dict(text=rows[0]['variants'][0],kind='RECALL',
                         ref_id='recall',numbers=[])]},rows,lang)[1]==1


def test_unrelated_audit_traffic_cannot_hide_delivery_checks(source):
    db,gw=source
    db.orders.insert_one({'_id':'order','kitchen_id':'k','status':'SENT','outcome':'SENT'})
    db.audit_log.insert_one({'server':{'kitchen_id':'k','at':NOW.isoformat()},
        'event':{'kind':'delivery_note_read','order_id':'order','statuses':{'SHORT':2}}})
    db.audit_log.insert_many([{'server':{'kitchen_id':'k','at':(NOW+timedelta(minutes=1)).isoformat()},
        'event':{'kind':'kitchen_brief_read'}} for _ in range(1001)])
    assert collect(gw,'k','evening','en')[0]['kind']=='DELIVERY_CHECK'


def test_morning_cutoff_skips_closing_times_already_passed(source):
    db, gw = source
    hel = timezone(timedelta(hours=2))
    ten = datetime(2026, 11, 14, 10, tzinfo=hel)
    gw.now = lambda: ten
    proposal(db, 'past', closing=datetime(2026, 11, 14, 8, tzinfo=hel))
    rows = collect(gw, 'k', 'morning', 'en')
    assert [r['kind'] for r in rows] == ['WAITING_DRAFTS']
    proposal(db, 'two', closing=datetime(2026, 11, 14, 8, tzinfo=hel))
    db.offers.update_one({'_id': 'two-offer'}, {'$push': {'simulation.lines': {
        'product_id': 'milk', 'quantity': '2', 'unit': 'L',
        'closing_time': datetime(2026, 11, 14, 15, tzinfo=hel)}}})
    cutoffs = [r for r in collect(gw, 'k', 'morning', 'en') if r['kind'] == 'CUTOFF']
    assert [r['ref_id'] for r in cutoffs] == ['two']
    text = cutoffs[0]['variants'][0]
    assert '2026-11-14 15:00' in text and '08:00' not in text
