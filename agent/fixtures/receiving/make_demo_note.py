"""Draw the delivery-note photo for the live demo kitchen's delivery beat (#1198; needs Pillow; run once).

    python agent/fixtures/receiving/make_demo_note.py

It matches the demo order that `python -m demo.delivery_order --apply` places for
demo-kitchen (reference DEMO-1198; demo/delivery_order.py LINES):

    463982 Kieku barn eggs L, 180 pcs        ordered 3 KI   on the note 1 KI  -> SHORT 2 KI
    460838 Cherry tomato 4 kg Finland        ordered 1 KI   not on the note   -> MISSING 1 KI
    463335 Valio Eila 3% milk drink 1 L      ordered 40 ST  on the note 40 ST -> RECEIVED

At the order's prices (EUR 31.01 and 29.06 a case) that is 3 cases short, EUR 91.08 ex VAT.
demo-note.reply.json is the reply a correct reader gives (written by hand from this truth,
not recorded from the live model).
"""
from make_notes import HERE, draw

LINES = [("463982", "Kieku barn eggs L, 180 pcs", "1", "KI", "K1411E", "2026-12-05", False),
         ("463335", "Valio Eila 3% milk drink 1 L lactose free", "40", "ST", "E1611M", "2026-11-26", False)]


if __name__ == "__main__":
    draw("demo-note", LINES, seed=1198, ref="DEMO-1198", day="2026-11-16")
    print("wrote", HERE / "demo-note.png")
