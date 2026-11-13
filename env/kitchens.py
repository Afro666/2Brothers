"""Kitchen types, recipes and the seeded set of kitchens.

Recipe quantities are per cover (one guest meal), in the product's kitchen unit.
"""

import random
from dataclasses import dataclass, field
from datetime import date

# Product codes, see env/catalog.py.
MILK, MILK_LF, CREAM, BUTTER, EGGS = "463171", "463335", "464194", "463437", "463982"
FLOUR, POTATO, CHICKEN, MINCE, SALMON = "460791", "460478", "462281", "463132", "461903"
RICE, PASTA, TOMATO, ONION, CARROT = "462279", "460008", "460838", "460351", "460811"
YOGHURT, EDAM, RYE, CUCUMBER, LETTUCE = "462718", "462616", "461578", "460137", "460026"
OATS, COFFEE, OIL = "460200", "461332", "464187"

RECIPES = {
    "macaroni_casserole": {PASTA: 0.07, MINCE: 0.06, ONION: 0.01, MILK: 0.04},
    "chicken_rice": {CHICKEN: 0.09, RICE: 0.06, CARROT: 0.04, YOGHURT: 0.02},
    "salmon_soup": {SALMON: 0.06, POTATO: 0.15, CREAM: 0.03, ONION: 0.01, CARROT: 0.02},
    "meatballs_potato": {MINCE: 0.08, POTATO: 0.18, FLOUR: 0.01, CREAM: 0.02, ONION: 0.01},
    "pasta_cream_chicken": {PASTA: 0.10, CREAM: 0.06, EDAM: 0.02, CHICKEN: 0.06},
    "baked_salmon": {SALMON: 0.14, POTATO: 0.20, BUTTER: 0.015, CREAM: 0.03},
    "roast_chicken": {CHICKEN: 0.16, POTATO: 0.20, CARROT: 0.05, OIL: 0.01},
    "burger": {MINCE: 0.16, LETTUCE: 0.02, TOMATO: 0.03, CUCUMBER: 0.01, OIL: 0.01, FLOUR: 0.03},
    "oat_porridge": {OATS: 0.05, MILK: 0.20, BUTTER: 0.005},
    "breakfast_buffet": {
        EGGS: 0.11, RYE: 1.5, BUTTER: 0.015, EDAM: 0.03, TOMATO: 0.03, CUCUMBER: 0.02,
        YOGHURT: 0.08, MILK_LF: 0.12, COFFEE: 0.012, OATS: 0.02,
    },
    "school_sides": {MILK: 0.20, RYE: 1.0, BUTTER: 0.007, LETTUCE: 0.025, CUCUMBER: 0.02},
    "hospital_sides": {MILK_LF: 0.15, RYE: 2.0, BUTTER: 0.01, YOGHURT: 0.10, COFFEE: 0.008},
    "restaurant_sides": {LETTUCE: 0.04, CUCUMBER: 0.02, TOMATO: 0.03, BUTTER: 0.01, RYE: 1.0, COFFEE: 0.01},
}

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


@dataclass(frozen=True)
class KitchenType:
    name: str
    base_covers: tuple  # (min, max) base covers per open day
    weekday: tuple  # factor per weekday Mon..Sun, 0 = closed
    fixed: tuple  # ((recipe, share), ...) served every open day
    mains: tuple  # rotating main dish, one per day (empty = none)
    main_share: float  # share of covers that get the rotating main
    delivery_days: tuple  # weekdays Valio delivers; order the day before
    holiday_weeks: tuple = ()  # ISO weeks with zero covers
    season: tuple = ()  # ((month, factor), ...)


TYPES = {
    "school": KitchenType(
        "school", (250, 600), (1.0, 1.0, 1.0, 1.0, 0.92, 0, 0),
        (("school_sides", 1.0),),
        ("macaroni_casserole", "chicken_rice", "salmon_soup", "meatballs_potato", "pasta_cream_chicken"),
        1.0, (MON, WED, FRI), holiday_weeks=(42,),
    ),
    "hospital": KitchenType(
        "hospital", (150, 400), (1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 0.95),
        (("oat_porridge", 1.0), ("hospital_sides", 1.0)),
        ("chicken_rice", "salmon_soup", "meatballs_potato", "macaroni_casserole",
         "roast_chicken", "baked_salmon", "pasta_cream_chicken"),
        1.0, (MON, TUE, WED, THU, FRI, SAT),
    ),
    "hotel": KitchenType(
        "hotel", (80, 250), (0.75, 0.75, 0.8, 0.9, 1.25, 1.35, 0.9),
        (("breakfast_buffet", 1.0),),
        ("baked_salmon", "roast_chicken", "burger", "pasta_cream_chicken",
         "meatballs_potato", "baked_salmon", "burger"),
        0.35, (MON, WED, FRI, SAT),
        season=((8, 1.15), (9, 1.0), (10, 0.95), (11, 0.9)),
    ),
    "restaurant": KitchenType(
        "restaurant", (60, 180), (0, 0.7, 0.8, 0.95, 1.3, 1.4, 0.6),
        (("restaurant_sides", 1.0), ("burger", 0.3), ("baked_salmon", 0.25),
         ("roast_chicken", 0.25), ("pasta_cream_chicken", 0.2)),
        (), 0.0, (TUE, THU, FRI, SAT),
        season=((8, 1.05), (9, 1.0), (10, 0.95), (11, 1.0)),
    ),
}

CITIES = ["Helsinki", "Espoo", "Vantaa", "Tampere", "Turku", "Oulu", "Jyvaskyla", "Lahti", "Kuopio", "Pori"]
MIX = ["school"] * 5 + ["hospital"] * 4 + ["hotel"] * 5 + ["restaurant"] * 6


@dataclass
class Kitchen:
    id: str
    name: str
    type: KitchenType
    city: str
    base_covers: int
    products: list = field(default_factory=list)

    def factor(self, day: date) -> float:
        """Expected covers multiplier for a day (weekday x season x holiday)."""
        if day.isocalendar()[1] in self.type.holiday_weeks:
            return 0.0
        season = dict(self.type.season).get(day.month, 1.0)
        return self.type.weekday[day.weekday()] * season

    def is_open(self, day: date) -> bool:
        return self.factor(day) > 0

    def menu(self, day: date) -> list:
        """[(recipe, share), ...] served on that day."""
        items = list(self.type.fixed)
        if self.type.mains:
            items.append((self.type.mains[day.toordinal() % len(self.type.mains)], self.type.main_share))
        return items

    def usage_per_cover(self, day: date) -> dict:
        """Expected product use per cover on that day {product_id: qty}."""
        use = {}
        for recipe, share in self.menu(day):
            for pid, qty in RECIPES[recipe].items():
                use[pid] = use.get(pid, 0.0) + qty * share
        return use


def make_kitchens(n: int, seed: int) -> list:
    """n kitchens with the fixed type mix (school, hospital, hotel, restaurant)."""
    rng = random.Random(f"kitchens-{seed}")
    out, count = [], {}
    for i in range(n):
        ktype = TYPES[MIX[i % len(MIX)]]
        count[ktype.name] = count.get(ktype.name, 0) + 1
        city = rng.choice(CITIES)
        kitchen = Kitchen(
            id=f"K{i + 1:02d}",
            name=f"{ktype.name.title()} {count[ktype.name]} {city}",
            type=ktype,
            city=city,
            base_covers=rng.randint(*ktype.base_covers),
        )
        used = set()
        for recipe, _ in ktype.fixed:
            used |= set(RECIPES[recipe])
        for recipe in ktype.mains:
            used |= set(RECIPES[recipe])
        kitchen.products = sorted(used)
        out.append(kitchen)
    return out
