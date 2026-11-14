"""Typed OpenAPI request bodies for the public Buyer workflow.

These models document the existing contract. Runtime parsing stays in app/service:
changing the validation boundary would alter auth precedence and error envelopes.
"""
from copy import deepcopy
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1)]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra='allow')


class PackSize(RequestBody):
    value: float
    unit: str = Field(description='L, DL, CL, ML, KG or G; case-insensitive.')


class ProductFilters(RequestBody):
    exclude_allergens: list[str] = Field(default_factory=list)
    allergen_strictness: Literal['declared', 'strict'] = 'declared'
    require_labels: list[str] = Field(default_factory=list)
    temperature: Literal['ambient', 'chilled', 'frozen'] | None = None
    category: str | None = None
    pack_size: PackSize | None = None
    supplier_id: str | None = None


class SearchProductsRequest(RequestBody):
    query: str = Field(default='', description='May be empty when a filter is supplied.')
    filters: ProductFilters = Field(default_factory=ProductFilters)
    limit: int = Field(default=20, ge=1, le=50)
    need_id: Identifier | None = Field(default=None, description='Scopes results to the stored need and its delivery date.')


class CreateNeedRequest(RequestBody):
    quantity: str = Field(description='Positive decimal string, e.g. "1000".')
    unit: str = Field(min_length=1, description='Requested measure, e.g. L, KG or the sales unit.')
    requested_date: date
    text: str = ''
    event: bool = Field(default=False, description='Trusted application flag for one-off demand; never set by the model.')


class GetOfferRequest(RequestBody):
    product_ids: list[Identifier] = Field(min_length=1, max_length=50)
    requested_date: date | None = Field(default=None, description='Optional; when given it must match the stored need. Quantity/unit come only from that need.')
    need_id: Identifier


class SimulateOrderRequest(RequestBody):
    offer_id: Identifier


class RequestApprovalRequest(SimulateOrderRequest):
    idempotency_key: Identifier


class PlaceOrderRequest(RequestApprovalRequest):
    expected_total: str = Field(pattern=r'^\d+\.\d{2}$', description='Exact simulated total. Only an already human-approved order can be returned.')


def document_body(model: type[BaseModel]) -> dict:
    """Inline nested definitions so every OpenAPI reference resolves without a hook.

    The documentation models above are acyclic. Local $defs references must be
    expanded: leaving them nested under requestBody would point at the spec root.
    """
    schema = model.model_json_schema()
    definitions = schema.pop('$defs', {})

    def inline(value):
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            name = value['$ref'].removeprefix('#/$defs/')
            return {**inline(deepcopy(definitions[name])),
                    **inline({k: v for k, v in value.items() if k != '$ref'})}
        return {k: inline(v) for k, v in value.items()}

    return {'requestBody': {'required': True, 'content': {'application/json': {'schema': inline(schema)}}}}
