"""Draw the two synthetic delivery-note photos for #362 (needs Pillow; run once).

    python agent/fixtures/receiving/make_notes.py

complete.png: the milk order 462775 x 51 ST delivered in two lots; one best-before is
smudged, so a reader must answer "unknown" for it.
short.png: only 36 ST of 462775, plus 2 KI of 462921 marked as a substitute.
"""
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
FONT = "C:/Windows/Fonts/arial.ttf"
BOLD = "C:/Windows/Fonts/arialbd.ttf"
MONO = "C:/Windows/Fonts/consola.ttf"

HEAD = ("Code", "Product", "Qty", "Unit", "Lot", "Best before")
X = (60, 190, 720, 800, 880, 1040)
NOTES = {
    "complete": [("462775", "Arla 1 L lactose free fat free UHT", "30", "ST", "L2611A", "2026-11-28", False),
                 ("462775", "Arla 1 L lactose free fat free UHT", "21", "ST", "L2611B", "2026-12-02", True)],
    "short": [("462775", "Arla 1 L lactose free fat free UHT", "36", "ST", "L2611A", "2026-11-28", False),
              ("462921", "Valio Eila organic 1 L (5 x 1 L)", "2", "KI", "E3011C", "2026-11-30", False)],
}


def draw(name, lines, seed):
    rnd = random.Random(seed)
    img = Image.new("RGB", (1240, 900), (250, 248, 240))
    d = ImageDraw.Draw(img)
    f, b, m = ImageFont.truetype(FONT, 26), ImageFont.truetype(BOLD, 34), ImageFont.truetype(MONO, 26)
    d.text((60, 50), "DELIVERY NOTE / LAHETE", font=b, fill=(20, 20, 20))
    d.text((60, 100), "SYNTHETIC TEST NOTE - not a real supplier document", font=f, fill=(150, 30, 30))
    d.text((60, 150), "Supplier: Valio (demo)      Customer: demo-kitchen", font=f, fill=(20, 20, 20))
    d.text((60, 190), "Order ref: ORD-DEMO-0001     Delivery date: 2026-11-16", font=f, fill=(20, 20, 20))
    y = 260
    for x, h in zip(X, HEAD):
        d.text((x, y), h, font=ImageFont.truetype(BOLD, 24), fill=(20, 20, 20))
    d.line((50, y + 36, 1190, y + 36), fill=(60, 60, 60), width=2)
    y += 56
    for code, product, qty, unit, lot, bb, smudge in lines:
        for x, v, font in zip(X, (code, product, qty, unit, lot, bb), (m, f, m, m, m, m)):
            d.text((x, y), v, font=font, fill=(25, 25, 25))
        if smudge:   # a wet thumb across the best-before date
            for _ in range(900):
                cx, cy = 1040 + rnd.randint(0, 150), y + rnd.randint(-6, 30)
                r = rnd.randint(3, 9)
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(95 + rnd.randint(0, 40),) * 3)
        y += 50
        if code == "462921":
            d.text((190, y), "SUBSTITUTE - replaces 462775 (short stock)", font=f, fill=(150, 30, 30))
            y += 50
    d.line((50, y + 10, 1190, y + 10), fill=(60, 60, 60), width=2)
    d.text((60, y + 40), "Received by: ______________     Signature: ______________", font=f, fill=(20, 20, 20))
    img = img.rotate(rnd.uniform(-2.0, 2.0), resample=Image.BICUBIC, expand=True, fillcolor=(70, 66, 60))
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    px = img.load()
    for _ in range(25000):   # sensor noise
        x, y2 = rnd.randrange(img.width), rnd.randrange(img.height)
        v = rnd.randint(-25, 25)
        r, g, bl = px[x, y2]
        px[x, y2] = (max(0, min(255, r + v)), max(0, min(255, g + v)), max(0, min(255, bl + v)))
    img.save(HERE / f"{name}.png", optimize=True)


if __name__ == "__main__":
    for i, (name, lines) in enumerate(NOTES.items()):
        draw(name, lines, seed=362 + i)
        print("wrote", HERE / f"{name}.png")
