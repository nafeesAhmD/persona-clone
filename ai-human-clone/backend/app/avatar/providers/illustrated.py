"""Built-in illustrated avatars, drawn locally with Pillow.

No model, no network and no real person's face: a good default for owners who
don't want to upload a photo. Because the drawing is ours, the mouth position
is exact, which gives clean lip-sync.
"""

from PIL import Image, ImageDraw, ImageFilter

from app.avatar.base import AvatarImage, AvatarProvider, AvatarStyle, MouthPosition
from app.avatar.image_processor import to_png

SIZE = 512
_SCALE = 2  # drawn at 2x and scaled down for smooth edges

PRESETS: dict[str, AvatarStyle] = {
    "ayaan": AvatarStyle(skin="#b98a68", hair="#1f1a17", hair_style="short", background="#3b4a8f", shirt="#2d6a8a"),
    "sara": AvatarStyle(skin="#c99a7a", hair="#2a1d17", hair_style="long", background="#2f7a78", shirt="#8a3d5c"),
    "zara": AvatarStyle(skin="#8d5f45", hair="#140f0d", hair_style="bun", background="#6b4a8f", shirt="#c47a2c"),
    "sam": AvatarStyle(skin="#e0b89a", hair="#6b4a2f", hair_style="short", background="#4a6b3b", shirt="#39465c"),
    "neo": AvatarStyle(skin="#a8795b", hair="#3a3a3a", hair_style="none", background="#233044", shirt="#5a5f73"),
}

_MOUTH = (256, 312)  # at SIZE
_MOUTH_WIDTH = 64


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in color)  # type: ignore[return-value]


class IllustratedAvatarProvider(AvatarProvider):
    name = "illustrated"

    def presets(self) -> dict[str, AvatarStyle]:
        return PRESETS

    def generate(self, style: AvatarStyle) -> AvatarImage:
        s = _SCALE
        skin, hair, bg, shirt = _rgb(style.skin), _rgb(style.hair), _rgb(style.background), _rgb(style.shirt)
        image = Image.new("RGB", (SIZE * s, SIZE * s), bg)
        draw = ImageDraw.Draw(image)

        # Background: soft vertical gradient.
        for y in range(SIZE * s):
            draw.line([(0, y), (SIZE * s, y)], fill=_shade(bg, 1.15 - 0.4 * y / (SIZE * s)))

        def box(x0: float, y0: float, x1: float, y1: float) -> list[float]:
            return [x0 * s, y0 * s, x1 * s, y1 * s]

        if style.hair_style == "long":  # hair behind the head and shoulders
            draw.rounded_rectangle(box(134, 110, 378, 430), radius=110 * s, fill=hair)
        draw.ellipse(box(76, 400, 436, 640), fill=shirt)  # shoulders
        draw.rectangle(box(222, 330, 290, 420), fill=_shade(skin, 0.88))  # neck
        draw.ellipse(box(222, 390, 290, 430), fill=_shade(skin, 0.88))
        draw.ellipse(box(136, 214, 170, 278), fill=_shade(skin, 0.95))  # ears
        draw.ellipse(box(342, 214, 376, 278), fill=_shade(skin, 0.95))
        draw.ellipse(box(150, 96, 362, 368), fill=skin)  # head

        if style.hair_style in ("short", "long", "bun"):
            draw.chord(box(144, 84, 368, 250), start=180, end=360, fill=hair)
            draw.ellipse(box(150, 92, 250, 170), fill=hair)
            draw.ellipse(box(262, 92, 362, 170), fill=hair)
        if style.hair_style == "bun":
            draw.ellipse(box(212, 44, 300, 124), fill=hair)

        # Cheeks.
        cheeks = Image.new("RGBA", image.size, (0, 0, 0, 0))
        cheek_draw = ImageDraw.Draw(cheeks)
        for x in (190, 322):
            cheek_draw.ellipse(box(x - 26, 276, x + 26, 304), fill=(230, 120, 120, 70))
        blurred = cheeks.filter(ImageFilter.GaussianBlur(10 * s))
        image.paste(blurred, (0, 0), blurred)
        draw = ImageDraw.Draw(image)

        # Eyes, brows, nose.
        for x in (208, 304):
            draw.ellipse(box(x - 20, 218, x + 20, 244), fill=(250, 250, 250))
            draw.ellipse(box(x - 10, 220, x + 10, 242), fill=(58, 40, 30))
            draw.ellipse(box(x - 4, 225, x + 2, 231), fill=(255, 255, 255))
            draw.line(box(x - 24, 202, x + 22, 198), fill=_shade(hair, 1.1), width=6 * s)
        draw.arc(box(240, 244, 272, 290), start=40, end=140, fill=_shade(skin, 0.7), width=4 * s)

        # Closed mouth: the lip line is at _MOUTH, where the lip-sync opens it.
        mx, my = _MOUTH
        lips = _shade(_rgb("#b5545c"), 0.95 if sum(skin) > 450 else 0.8)
        draw.chord(box(mx - 32, my - 8, mx + 32, my + 14), start=0, end=180, fill=lips)
        draw.line(box(mx - 32, my, mx + 32, my), fill=_shade(lips, 0.6), width=3 * s)

        image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
        return AvatarImage(
            png=to_png(image),
            width=SIZE,
            height=SIZE,
            mouth=MouthPosition(x=mx / SIZE, y=my / SIZE, width=_MOUTH_WIDTH / SIZE),
            face_detected=True,
            faces_found=1,
        )
