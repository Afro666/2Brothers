"""Kitchen-unit precision for synthetic forecasts exported to the demo."""
import math


def forecast_quantity(value: float, unit: str) -> int | float:
    """Counted needs round up to a whole piece; weights/volumes keep 3 decimals."""
    # Round away float noise first so 30 * 0.1 (3.0000000000000004) stays 3.
    return math.ceil(round(value, 6)) if unit.upper() in ('PCS', 'ST') else round(value, 3)
