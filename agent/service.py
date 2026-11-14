"""Internal bounded Nemotron worker; proposes only, never approves or orders."""
import asyncio
from datetime import date, datetime, timedelta
import hmac
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.shared.memory import create_connected_server_and_client_session

from agent.model import Nemotron
from agent.runner import Buyer
from agent.usage import emit
from agent.memory_cache import KitchenFactsCache
from gateway import model_trace
from gateway.mcp_server import GatewayClient, build_server
from store import agent_runs
from store import buyer_context
from agent.substitutes import AllergenPolicy, SubstitutePlanner
from store.orders import IdempotencyConflict


class WorkerError(Exception):
    def __init__(self, status, code, *, fallback_safe=False):
        self.status, self.code, self.fallback_safe = status, code, fallback_safe


def parse_need(body, *, today=None):
    """Extract only an unambiguous explicit quantity; never ask a model to size it."""
    text = body.get('text')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        raise WorkerError(422, 'INVALID_REQUEST')
    matches = re.findall(r'(?<![\w.,+\-])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(litres?|liters?|kg|kilograms?|pcs|pieces?|l)\b', text, re.I)
    if len(matches) != 1:
        raise WorkerError(422, 'NEED_DETAILS', fallback_safe=True)
    quantity, unit = matches[0]
    quantity = quantity.replace(',', '')
    if not 0 < float(quantity) <= 1_000_000:
        raise WorkerError(422, 'INVALID_QUANTITY')
    unit = 'L' if unit.lower() in ('l', 'litre', 'litres', 'liter', 'liters') else ('KG' if unit.lower() in ('kg', 'kilogram', 'kilograms') else 'PCS')
    requested = body.get('requested_date')
    if requested is None:
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        mentioned = [i for i, day in enumerate(days) if re.search(r'\b' + day + r'\b', text, re.I)]
        if len(mentioned) != 1:
            raise WorkerError(422, 'NEED_DATE', fallback_safe=True)
        today = today or datetime.now(ZoneInfo('Europe/Helsinki')).date()
        requested = (today + timedelta(days=(mentioned[0] - today.weekday()) % 7 or 7)).isoformat()
    try:
        requested = date.fromisoformat(requested).isoformat()
    except (ValueError, TypeError):
        raise WorkerError(422, 'INVALID_DATE') from None
    need = {'quantity': quantity, 'unit': unit, 'requested_date': requested, 'text': text.strip()}
    if body.get('event') is True:
        need['event'] = True    # one-off demand: the gateway marks every line EVENT_LINE (#530)
    return need


class BuyerWorker:
    def __init__(self, db, gateway, *, model_factory=None, timeout=None, now=None, strategy=None):
        self.strategy = strategy or os.environ.get('NEMOTRON_BUYER_STRATEGY', 'single_pick')
        if self.strategy not in ('single_pick', 'loop'):
            raise ValueError('invalid Buyer strategy')
        self.db, self.gateway = db, gateway
        self.model_factory = model_factory or ((lambda: Nemotron(max_attempts=1))
                                               if self.strategy == 'single_pick' else Nemotron)
        self.timeout = timeout if timeout is not None else (35 if self.strategy == 'single_pick' else 150)
        self.now = now
        self.memory_cache = KitchenFactsCache()

    async def run(self, kitchen_id, body):
        need = parse_need(body)
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not 1 <= len(key.strip()) <= 200:
            raise WorkerError(422, 'MISSING_IDEMPOTENCY_KEY')
        exclusions = buyer_context.excluded_allergens(self.db, kitchen_id)
        try:
            policy = AllergenPolicy(tuple(exclusions)) if exclusions is not None else None
        except ValueError:
            # A misspelt allergen code must never silently widen what is safe: fail closed.
            raise WorkerError(503, 'KITCHEN_POLICY_INVALID', fallback_safe=True) from None
        try:
            row, created = agent_runs.claim(self.db, kitchen_id, key, need)
        except IdempotencyConflict:
            raise WorkerError(409, 'IDEMPOTENCY_KEY_REUSED') from None
        if not created:
            if row['state'] == 'READY':
                return row['result']
            raise WorkerError(409, 'BUYER_RECONCILIATION_REQUIRED')
        model, buyer, status = None, None, 'FAILED'
        async def execute():
            nonlocal model, buyer
            stored = await self.gateway.request('POST', f'/v1/kitchens/{kitchen_id}/needs', payload=need)
            model = self.model_factory()
            lookup = lambda pid: buyer_context.product(self.db, kitchen_id, pid)
            # The model does not finish every run (seen live: about 1 in 3 stopped without asking
            # for approval). A run that wrote nothing is safe to start once more, under its own
            # run id so its audit steps stay separate. A run that wrote something is never repeated.
            steps = []
            for attempt in ((1,) if self.strategy == 'single_pick' else (1, 2)):
                run_id = row['_id'] if attempt == 1 else f"{row['_id']}-retry"
                selected_model = model
                if self.strategy == 'single_pick':
                    from agent.single_pick import SinglePickModel
                    clock = self.now() if self.now else datetime.now(ZoneInfo('Europe/Helsinki'))
                    selected_model = SinglePickModel(model, self.db, kitchen_id, need, stored['need_id'],
                                                    exclusions, today=clock.date(), memory_cache=self.memory_cache)
                async with create_connected_server_and_client_session(build_server(self.gateway)) as session:
                    buyer = Buyer(selected_model, session, self.gateway, need_id=stored['need_id'],
                                  requested_date=need['requested_date'],
                                  run_id=run_id,
                                  max_steps=12, now=self.now,
                                  catalog_lookup=lookup, allergen_policy=policy,
                                  substitute_planner=SubstitutePlanner(lookup, policy) if policy else None,
                                  attempt=attempt)
                    outcome = await buyer.run(need['text'])
                if self.strategy == 'single_pick':
                    # The new trace distinguishes host orchestration from the one model pick.
                    trace = [{**step, 'by': 'code'} for step in buyer.trace]
                    if selected_model.selected_ids:
                        trace.insert(2, model_trace.step('pick', by='code' if selected_model.cached else 'model',
                            attempt=attempt, products=len(selected_model.selected_ids),
                            code='CACHED_PICK' if selected_model.cached else 'PICKED'))
                    steps += trace
                else:
                    steps += buyer.trace
                if getattr(selected_model, 'timed_out', False):
                    raise WorkerError(504, 'BUYER_TIMEOUT', fallback_safe=not buyer.mutations)
                if outcome['status'] == 'SENT_FOR_APPROVAL' or buyer.mutations:
                    break
            if outcome['status'] != 'SENT_FOR_APPROVAL':
                raise WorkerError(503, 'BUYER_INCOMPLETE', fallback_safe=not buyer.mutations)
            proposal_id = outcome.get('proposal_id')
            result = None
            if isinstance(proposal_id, str) and proposal_id.strip() and len(proposal_id) <= 200:
                result = await self.gateway.request('GET',
                    f'/v1/kitchens/{kitchen_id}/proposals/{quote(proposal_id, safe="")}')
                if result.get('proposal_id') != proposal_id or result.get('approval_id') != outcome['approval_id']:
                    result = None
            elif proposal_id is None:
                # Compatibility with older gateways only. Never fall back after an ID mismatch.
                proposals = await self.gateway.request('GET', f'/v1/kitchens/{kitchen_id}/proposals')
                result = next((p for p in proposals['proposals'] if p.get('approval_id') == outcome['approval_id']), None)
            if result is None:
                raise WorkerError(503, 'BUYER_RECONCILIATION_REQUIRED')
            if outcome.get('substitute_options'):
                buyer_context.save_options(self.db, kitchen_id, result['proposal_id'], outcome['substitute_options'])
                result['substitute_options'] = outcome['substitute_options']
            result = {**result, 'buyer_run_id': run_id, 'buyer_model': 'nemotron-3.5-super-vl'}
            meter = getattr(model, 'meter', None)
            if meter is not None:
                # Model calls, tokens and seconds of this request, both attempts (agent/usage.py).
                result['buyer_usage'] = meter.total()
            # What the model did (#1197): kept with the run, served on the proposal later.
            result['model_trace'] = model_trace.build(
                reader='buyer', made_by='model', usage=meter.total() if meter is not None else None,
                thinking=False if self.strategy == 'single_pick' else getattr(model, 'thinking', None),
                steps=steps, attempts=attempt)
            return result
        try:
            result = await asyncio.wait_for(execute(), timeout=self.timeout)
            agent_runs.finish(self.db, row['_id'], state='READY', result=result)
            status = 'READY'
            return result
        except asyncio.TimeoutError:
            agent_runs.finish(self.db, row['_id'], state='RECONCILE', result=None)
            raise WorkerError(504, 'BUYER_TIMEOUT', fallback_safe=buyer is None or not buyer.mutations) from None
        except Exception as exc:
            agent_runs.finish(self.db, row['_id'], state='RECONCILE', result=None)
            if isinstance(exc, WorkerError):
                raise
            raise WorkerError(503, 'BUYER_UNAVAILABLE', fallback_safe=buyer is None or not buyer.mutations) from None
        finally:
            if model is not None:
                emit(getattr(model, 'meter', None), run='buyer', status=status,
                     strategy=self.strategy,
                     thinking=False if self.strategy == 'single_pick' else getattr(model, 'thinking', None),
                     max_tokens=512 if self.strategy == 'single_pick' else getattr(model, 'max_tokens', None))
                await model.close()


def create_app(worker=None, shelf=None, delivery_note=None, menu_photo=None, buying_note=None, price_list=None, explanation=None, label_photo=None):
    state = {}
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if state:
                await state['worker'].gateway.close()
    app = FastAPI(title='Internal Nemotron Buyer', lifespan=lifespan)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.exception_handler(WorkerError)
    async def error(request, exc):
        return JSONResponse(status_code=exc.status, content={'error': {
            'code': exc.code, 'message': 'Buyer request did not complete; check request details or reconcile the existing run.',
            'fallback_safe': exc.fallback_safe}})

    @app.post('/run')
    async def run(request: Request):
        token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
        given = request.headers.get('authorization', '')
        if not token or not hmac.compare_digest(given.encode(), ('Bearer ' + token).encode()):
            raise WorkerError(401, 'UNAUTHENTICATED')
        try:
            body = await request.json()
        except ValueError:
            raise WorkerError(422, 'INVALID_REQUEST') from None
        if not isinstance(body, dict):
            raise WorkerError(422, 'INVALID_REQUEST')
        kitchen = os.environ.get('GATEWAY_KITCHEN_ID', 'demo-kitchen')
        if body.get('kitchen_id') != kitchen:
            raise WorkerError(403, 'KITCHEN_SCOPE')
        current = worker
        try:
            if current is None:
                if not state:
                    from store.db import get_db
                    gateway = GatewayClient(token=token)
                    state['worker'] = BuyerWorker(get_db(), gateway)
                current = state['worker']
            return await current.run(kitchen, body)
        except WorkerError:
            raise
        except Exception:
            raise WorkerError(503, 'BUYER_UNAVAILABLE') from None

    # Snap the shelf (#373): POST /shelf reads a photo into a stock count to confirm.
    from agent.shelf_service import mount_shelf
    mount_shelf(app, WorkerError, shelf)
    # Delivery-note check (#362): POST /delivery-note reads a note and checks it against the order.
    from agent.receiving_service import mount_delivery_note
    mount_delivery_note(app, WorkerError, delivery_note)
    from agent.menu_photo_service import mount_menu_photo
    mount_menu_photo(app, WorkerError, menu_photo)
    from agent.brief_service import mount_brief
    mount_brief(app, WorkerError)
    from agent.buying_note_service import mount_buying_note
    mount_buying_note(app, WorkerError, buying_note)
    from agent.price_list_service import mount_price_list
    mount_price_list(app, WorkerError, price_list)
    from agent.explanation_service import mount_explanation
    mount_explanation(app, WorkerError, explanation)
    from agent.label_service import mount_label_photo
    mount_label_photo(app, WorkerError, label_photo)
    # Several products in one request (#1375): POST /split, one model call, checked by the gateway.
    from agent.split_service import mount_split
    mount_split(app, WorkerError)
    return app


def main():
    import uvicorn
    uvicorn.run('agent.service:create_app', factory=True, host='0.0.0.0', port=8001, access_log=False)
