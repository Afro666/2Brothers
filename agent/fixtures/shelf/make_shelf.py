"""Draw the synthetic walk-in fridge shelf photo for #373 (needs Pillow; run once).

    python agent/fixtures/shelf/make_shelf.py

Truth (see TRUTH): 7 Arla lactose free 1 L, 6 Eila 3 % 1 L, 4 Eila organic 1 L,
2 Eila 10 L novobox, and 1 Arla 10 L novobox half hidden behind them, so a careful
reader should say it is not sure about that one.
"""
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
FONT, BOLD = "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"
TRUTH = {"Arla lactose free 1 L": 7, "Valio Eila 3% 1 L": 6, "Valio Eila organic 1 L": 4,
         "Valio Eila 10 L novobox": 2, "Arla 10 L novobox": 1}


def carton(d, x, y, w, h, colour, band, lines, font):
    d.rectangle((x, y, x + w, y + h), fill=colour, outline=(40, 40, 40), width=2)
    d.polygon([(x, y), (x + w // 2, y - 22), (x + w, y)], fill=colour, outline=(40, 40, 40))   # gable top
    d.rectangle((x, y + h * 0.35, x + w, y + h * 0.62), fill=band)
    for i, text in enumerate(lines):
        d.text((x + 6, y + h * 0.37 + i * 22), text, font=font, fill=(255, 255, 255))


def box(d, x, y, w, h, colour, lines, font):
    d.rectangle((x, y, x + w, y + h), fill=colour, outline=(40, 40, 40), width=3)
    d.rectangle((x + 15, y + 30, x + w - 15, y + 110), fill=(250, 250, 250))
    for i, text in enumerate(lines):
        d.text((x + 25, y + 38 + i * 30), text, font=font, fill=(30, 30, 30))


def main():
    rnd = random.Random(373)
    img = Image.new("RGB", (1600, 1100), (205, 212, 218))
    d = ImageDraw.Draw(img)
    small, mid = ImageFont.truetype(BOLD, 17), ImageFont.truetype(BOLD, 24)
    for y in (430, 1010):   # shelf planks
        d.rectangle((0, y, 1600, y + 28), fill=(150, 155, 160), outline=(90, 90, 95))
    # Top shelf: 1 L cartons in three groups.
    x = 30
    for count, colour, band, lines in ((7, (235, 235, 240), (40, 90, 170), ["Arla", "lactose free", "1 L"]),
                                       (6, (245, 245, 245), (200, 40, 50), ["Valio Eila", "3% 1 L"]),
                                       (4, (240, 245, 235), (60, 140, 60), ["Valio Eila", "organic 1 L"])):
        for _ in range(count):
            carton(d, x, 230 + rnd.randint(-4, 4), 78, 200, colour, band, lines, small)
            x += 86
        x += 40
    # Bottom shelf: two Eila 10 L boxes in front, one Arla 10 L box half hidden behind them.
    box(d, 430, 690, 330, 320, (175, 140, 95), ["Arla", "10 L novobox"], mid)
    box(d, 150, 740, 330, 270, (190, 150, 100), ["Valio Eila", "10 L novobox"], mid)
    box(d, 520, 760, 330, 250, (190, 150, 100), ["Valio Eila", "10 L novobox"], mid)
    d.text((1150, 1050), "SYNTHETIC TEST PHOTO", font=small, fill=(120, 30, 30))
    img = img.rotate(rnd.uniform(-1.5, 1.5), resample=Image.BICUBIC, expand=False, fillcolor=(60, 60, 60))
    img = img.filter(ImageFilter.GaussianBlur(1.0))
    px = img.load()
    for _ in range(40000):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        v = rnd.randint(-20, 20)
        px[x, y] = tuple(max(0, min(255, c + v)) for c in px[x, y])
    img.save(HERE / "shelf.png", optimize=True)
    print("wrote", HERE / "shelf.png")


if __name__ == "__main__":
    main()
