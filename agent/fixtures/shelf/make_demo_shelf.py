"""Draw the synthetic shelf photo for the live demo kitchen (#373; needs Pillow; run once).

    python agent/fixtures/shelf/make_demo_shelf.py

shelf.png shows milk the demo kitchen does not stock, so on the live site its labels match
nothing. This photo prints the English catalog names of products that are on the demo
kitchen's stock list (demo-kitchen.json), so the Stock page's "Count from a photo" has
something to fill. Truth (see TRUTH): 6 Eila 3 % milk drink 1 l, 5 whipping cream 1 l,
4 rapeseed oil 1 l, 3 cooking yoghurt 2 kg, 4 butter 500 g, and 1 Edam 1 kg half hidden
behind the yoghurt, so a careful reader should say it is not sure about that one.
"""
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
FONT, BOLD = "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"
TRUTH = {"463335": 6, "464194": 5, "464187": 4, "462718": 3, "463437": 4, "462616": 1}


def pack(d, x, y, w, h, colour, lines, font, gable=True, step=21, label_top=None):
    d.rectangle((x, y, x + w, y + h), fill=colour, outline=(40, 40, 40), width=2)
    if gable:
        d.polygon([(x, y), (x + w // 2, y - 22), (x + w, y)], fill=colour, outline=(40, 40, 40))
    top = y + h * 0.30 if label_top is None else label_top
    d.rectangle((x + 4, top, x + w - 4, top + len(lines) * step + 10), fill=(250, 250, 250))
    for i, text in enumerate(lines):
        d.text((x + 8, top + 5 + i * step), text, font=font, fill=(25, 25, 25))


def main():
    rnd = random.Random(3731)
    img = Image.new("RGB", (1800, 1150), (205, 212, 218))
    d = ImageDraw.Draw(img)
    small, mid = ImageFont.truetype(BOLD, 15), ImageFont.truetype(BOLD, 22)
    for y in (440, 1040):   # shelf planks
        d.rectangle((0, y, 1800, y + 28), fill=(150, 155, 160), outline=(90, 90, 95))
    # Top shelf: 1 l cartons and bottles in three groups.
    x = 30
    for count, colour, lines in ((6, (200, 60, 70), ["Valio Eila", "3 % milk", "drink 1 l", "lactose free"]),
                                 (5, (70, 110, 180), ["Valio", "whipping", "cream 1 l", "UHT", "lactose free"]),
                                 (4, (225, 190, 70), ["Keiju", "Rapeseed", "oil 1 l"])):
        for _ in range(count):
            pack(d, x, 220 + rnd.randint(-4, 4), 100, 220, colour, lines, small)
            x += 108
        x += 40
    # Bottom shelf: one Edam pack half hidden behind three yoghurt buckets; four butter packs.
    pack(d, 470, 700, 260, 340, (230, 200, 90), ["Valio Edam 17 %", "1 kg slices"], mid, gable=False, step=30,
         label_top=742)   # only the first label line shows above the buckets
    for i in range(3):
        pack(d, 60 + i * 250, 780, 235, 260, (235, 235, 240),
             ["Valio Turkish", "cooking yoghurt", "2 kg lactose free"], mid, gable=False, step=30)
    for i in range(4):
        pack(d, 900 + i * 215, 880 + rnd.randint(-3, 3), 200, 160, (240, 225, 150),
             ["Valio Eila butter", "500 g salted", "lactose free"], mid, gable=False, step=30)
    d.text((1350, 1090), "SYNTHETIC TEST PHOTO", font=small, fill=(120, 30, 30))
    img = img.rotate(rnd.uniform(-1.5, 1.5), resample=Image.BICUBIC, expand=False, fillcolor=(60, 60, 60))
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    px = img.load()
    for _ in range(40000):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        v = rnd.randint(-20, 20)
        px[x, y] = tuple(max(0, min(255, c + v)) for c in px[x, y])
    img.save(HERE / "demo-shelf.png", optimize=True)
    print("wrote", HERE / "demo-shelf.png")


if __name__ == "__main__":
    main()
