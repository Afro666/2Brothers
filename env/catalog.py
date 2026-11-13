"""Real Valio Aimo products used by the simulation.

Product codes, sales units and pack sizes come from the challenge catalog. Prices are
Valio `/api/price` catalogPrice values (EUR, before tax, per sales unit) for customer
"123", delivery 2026-11-16, read 2026-11-13. Names are our own short English labels.
Shelf life and ABC class are our assumptions (the catalog has no shelf life field).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    unit: str  # kitchen unit for recipes and stock: L, KG or PCS
    pack: float  # kitchen units in one sales unit
    sales_unit: str  # Valio sales unit (KI = case, ST = piece, ...)
    price: float  # EUR before tax per sales unit
    shelf_life: int  # days a delivery stays usable
    abc: str  # A menu-critical, B normal, C garnish


_ROWS = [
    # id, name, unit, pack, sales_unit, price, shelf_life, abc
    ("463171", "Valio skimmed milk 1 L (case of 5)", "L", 5.0, "KI", 4.38, 10, "B"),
    ("463335", "Valio Eila 3% milk drink 1 L lactose free", "L", 1.0, "ST", 1.40, 10, "B"),
    ("464194", "Valio whipping cream 1 L UHT lactose free", "L", 1.0, "ST", 3.91, 30, "B"),
    ("463437", "Valio Eila butter 500 g lactose free", "KG", 0.5, "ST", 3.31, 60, "B"),
    ("463982", "Kieku barn eggs L, 180 pcs", "KG", 12.3, "KI", 31.01, 21, "A"),
    ("460791", "Myllyn Paras wheat flour 2 kg", "KG", 2.0, "BAG", 2.73, 180, "C"),
    ("460478", "Potato washed 1 kg", "KG", 1.0, "ST", 1.66, 21, "A"),
    ("462281", "Kariniemen chicken breast fillet", "KG", 1.0, "KG", 7.70, 6, "A"),
    ("463132", "Atria minced beef 17% 2 kg", "KG", 2.0, "ST", 28.97, 4, "A"),
    ("461903", "Salmon fillet A, ASC", "KG", 1.0, "KG", 24.85, 4, "A"),
    ("462279", "Risella wholewheat rice 5 kg", "KG", 5.0, "SK", 11.18, 365, "B"),
    ("460008", "Barilla fusilli 5 kg", "KG", 5.0, "BAG", 18.14, 365, "B"),
    ("460838", "Cherry tomato 4 kg Finland", "KG", 4.0, "KI", 29.06, 7, "C"),
    ("460351", "Onion 1 kg bag", "KG", 1.0, "ST", 0.86, 30, "C"),
    ("460811", "Carrot 1 kg bag Finland", "KG", 1.0, "BAG", 1.26, 21, "B"),
    ("462718", "Valio Turkish cooking yoghurt 2 kg lactose free", "KG", 2.0, "ST", 6.38, 14, "B"),
    ("462616", "Valio Edam 17% slices 1 kg", "KG", 1.0, "ST", 8.57, 30, "B"),
    ("461578", "Vaasan rye bread 45 x 85 g frozen", "PCS", 45.0, "CS", 16.02, 90, "B"),
    ("460137", "Cucumber Finland", "KG", 1.0, "KG", 3.46, 7, "C"),
    ("460026", "Iceberg lettuce", "KG", 1.0, "KG", 1.93, 5, "C"),
    ("460200", "Elovena wholegrain oat flakes 1 kg", "KG", 1.0, "ST", 2.76, 365, "B"),
    ("461332", "Kulta Katriina filter coffee 5 x 1 kg", "KG", 5.0, "KI", 72.65, 180, "B"),
    ("464187", "Keiju rapeseed oil 1 L", "L", 1.0, "BOT", 3.50, 365, "C"),
]

PRODUCTS = {row[0]: Product(*row) for row in _ROWS}
