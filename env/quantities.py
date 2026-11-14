"""Kitchen-unit precision for synthetic forecasts exported to the demo."""
import math


def forecast_quantity(value: float, unit: str) -> int | float:
    """Counted needs round up to a whole piece; weights/volumes keep 3 decimals."""
    # Suppress float arithmetic noise at integer boundaries before rounding up.
    return math.ceil(round(value, 6)) if unit.upper() in ('PCS', 'ST') else round(value, 3)
