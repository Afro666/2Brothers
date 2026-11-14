"""Independent covers models. Recipe explosion stays in the caller."""
import importlib.util
import logging

from env.history import Forecaster
from signals.covers import CoverSignals


class Current(Forecaster):
    name = "current"
    requires = ()

    def __init__(self, kitchen, signals=None):
        super().__init__(kitchen)


class RidgeCovers:
    """Ridge residuals around the planned pattern (alpha=10, fixed in advance).

    Fit only on observed days, using snapshots available on each observation day.
    A 21-day cold start uses the current model; closed days remain zero.
    """
    name = "ridge"
    requires = ("numpy", "holidays")      # holidays: the calendar features (signals/covers.py)

    def __init__(self, kitchen, signals=None):
        self.kitchen = kitchen
        self.signals = signals or CoverSignals(kitchen)
        self.fallback = Current(kitchen)
        self.history = []
        self.origin = None
        self.coef = None
        self.predictions = {}

    def observe(self, day, covers):
        if self.origin is not None and day <= self.origin:
            raise ValueError("observations must advance in time")
        self.fallback.observe(day, covers)
        self.history.append((day, covers))
        self.origin = day
        self.coef = None
        self.predictions.clear()

    def __call__(self, day):
        if self.origin is not None and day <= self.origin:
            raise ValueError("forecast target must follow the last observation")
        if not self.kitchen.is_open(day):
            return 0.
        if len(self.history) < 21:
            return self.fallback(day)
        if day in self.predictions:
            return self.predictions[day]
        import numpy as np
        if self.coef is None:
            rows = [(d, y) for d, y in self.history if self.kitchen.is_open(d)]
            x = np.asarray([[1.] + self.signals.features(d, d) for d, _ in rows])
            y = np.asarray([c / self.kitchen.base_covers - self.kitchen.factor(d) for d, c in rows])
            penalty = np.eye(x.shape[1]) * 10.
            penalty[0, 0] = 0.1
            self.coef = np.linalg.solve(x.T @ x + penalty, x.T @ y)
        features = np.asarray([1.] + self.signals.features(day, self.origin))
        prediction = max(0., float(self.kitchen.base_covers * (self.kitchen.factor(day) + features @ self.coef)))
        self.predictions[day] = prediction
        return prediction


class ETSCovers(RidgeCovers):
    """Statsmodels additive level + weekly seasonality; refit at each origin."""
    name = "ets"
    requires = ("numpy", "statsmodels")

    def __call__(self, day):
        if self.origin is not None and day <= self.origin:
            raise ValueError("forecast target must follow the last observation")
        if not self.kitchen.is_open(day):
            return 0.
        if len(self.history) < 21:
            return self.fallback(day)
        if day in self.predictions:
            return self.predictions[day]
        if self.coef is None:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            self.coef = ExponentialSmoothing(
                [y for _, y in self.history], trend=None, seasonal="add",
                seasonal_periods=7, initialization_method="estimated").fit()
            # The ordering policy checks shelf-life caps up to a year ahead.
            # Calculate the ETS path once per origin, rather than once per day
            # and ingredient. Longer requested horizons expand the same path.
            self.ets_path = self.coef.forecast(366)
        step = (day - self.origin).days
        if step > len(self.ets_path):
            self.ets_path = self.coef.forecast(step)
        prediction = max(0., float(self.ets_path[step - 1]))
        self.predictions[day] = prediction
        return prediction


MODELS = {m.name: m for m in (Current, RidgeCovers, ETSCovers)}

# The full six-seed comparison retains current for every kitchen type: neither
# candidate passes the holdout cost/lost-covers/waste gate. See env/BACKTEST.md.
SELECTED = {kind: "current" for kind in ("school", "hospital", "hotel", "restaurant")}


log = logging.getLogger(__name__)


def missing_deps(model) -> list[str]:
    """The packages a covers model needs that this install lacks (the `covers` extra)."""
    return [name for name in model.requires if importlib.util.find_spec(name) is None]


def demo_forecaster(kitchen, signals=None):
    """The SELECTED model for the kitchen type. The demo/deploy install has only the base
    deps (#1039): when the model's packages are missing, use `current` and say so, so a
    future backtest result can never crash demo seeding halfway."""
    model = MODELS[SELECTED[kitchen.type.name]]
    missing = missing_deps(model)
    if missing:
        log.warning("covers model %r needs %s (pip install '.[covers]'); using 'current' for %s",
                    model.name, ", ".join(missing), kitchen.type.name)
        model = Current
    return model(kitchen, signals)
