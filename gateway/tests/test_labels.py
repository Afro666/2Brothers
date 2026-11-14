from datetime import datetime, timezone
import mongomock
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.service import Gateway
from monitor.labels import LABEL


def test_authenticated_route_shows_three_real_claims_and_explicit_synthetic_negative(monkeypatch):
    monkeypatch.setenv('GATEWAY_HUMAN_TOKEN', 'human-test')
    db = mongomock.MongoClient(tz_aware=True).db
    for pid in ('462535', '462576', '462775'):
        db.products.insert_one({'_id': pid, 'vendor': 'ARLA OY', 'labels': [LABEL]})
    gw = Gateway(db, None, now=lambda: datetime(2026, 11, 14, 2, tzinfo=timezone.utc))
    client = TestClient(create_app(gw))
    path = '/v1/kitchens/demo-kitchen/label-checks'
    assert client.get(path).status_code == 401
    response = client.get(path, headers={'Authorization': 'Bearer human-test', 'X-User': 'chef'})
    assert response.status_code == 200
    result = response.json()
    assert len(result['checks']) == 3
    assert all(c['label_verified'] is True and c['scope'] == 'producer' for c in result['checks'])
    assert result['negative_control']['label_verified'] == 'not_found'
    assert result['negative_control']['synthetic'] is True
    assert db.orders.count_documents({}) == 0
