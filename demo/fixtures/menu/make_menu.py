"""Make the prepared menu photo for the menu-photo demo (#1136).

A typed menu of five dishes, one per weekday, each with its covers. The dish names are
recipe names of the live demo kitchen (`GET /v1/kitchens/demo-kitchen/recipes`, read on
2026-11-14), so every dish should match a recipe. Nothing on the sheet is a quantity:
the engine sizes the order, and a person approves it.

Run from the repo root:

    python demo/fixtures/menu/make_menu.py

It writes `demo/fixtures/menu/menu.png` next to this file. It needs Pillow only.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "menu.png"

TITLE = "Lunch menu, week 48"
SUBTITLE = "Demo kitchen, 23 to 27 November 2026"

# (weekday, dish = a demo-kitchen recipe name, covers)
DISHES: list[tuple[str, str, int]] = [
    ("Monday", "Salmon soup", 120),
    ("Tuesday", "Meatballs potato", 140),
    ("Wednesday", "Macaroni casserole", 130),
    ("Thursday", "Roast chicken", 110),
    ("Friday", "Pasta cream chicken", 120),
]

WIDTH, HEIGHT = 1200, 1600
PAPER = (250, 247, 240)
INK = (30, 30, 30)
MUTED = (100, 100, 100)
RULE = (200, 195, 185)

# Common fonts first; Pillow's own font when none is installed.
FONT_FILES = ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")
BOLD_FILES = (
    "arialbd.ttf",
    "Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
)


def font(
    size: int, *, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in BOLD_FILES if bold else FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    margin = 110
    draw.text((margin, 120), TITLE, font=font(72, bold=True), fill=INK)
    draw.text((margin, 220), SUBTITLE, font=font(40), fill=MUTED)
    draw.line((margin, 300, WIDTH - margin, 300), fill=INK, width=4)

    top = 360
    row = 220
    for index, (day, dish, covers) in enumerate(DISHES):
        y = top + index * row
        draw.text((margin, y), day, font=font(44, bold=True), fill=INK)
        draw.text((margin, y + 64), dish, font=font(58), fill=INK)
        draw.text((margin, y + 140), f"{covers} covers", font=font(40), fill=MUTED)
        if index < len(DISHES) - 1:
            draw.line(
                (margin, y + row - 24, WIDTH - margin, y + row - 24), fill=RULE, width=2
            )
    return image


def main() -> None:
    render().save(OUT, format="PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
