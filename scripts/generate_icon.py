"""Generate integration icons (icon.png + icon@2x.png) using Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GREEN = (30, 190, 105)  # #1EBE69
WHITE = (255, 255, 255)
DEST = Path(__file__).resolve().parent.parent / "custom_components" / "ev_charge_planner"


def draw_icon(size: int) -> Image.Image:
    """Draw a simple EV charging icon: car silhouette with lightning bolt."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size  # shorthand
    DARK = (20, 140, 75)  # darker green for wheels

    # Circular background
    draw.ellipse([0, 0, s - 1, s - 1], fill=GREEN)

    # Car body — rounded rectangle
    body_left = int(s * 0.15)
    body_right = int(s * 0.85)
    body_top = int(s * 0.40)
    body_bottom = int(s * 0.64)
    draw.rounded_rectangle(
        [body_left, body_top, body_right, body_bottom],
        radius=int(s * 0.06),
        fill=WHITE,
    )

    # Car roof — trapezoid-ish rounded rectangle
    roof_left = int(s * 0.28)
    roof_right = int(s * 0.68)
    roof_top = int(s * 0.25)
    roof_bottom = body_top + int(s * 0.03)
    draw.rounded_rectangle(
        [roof_left, roof_top, roof_right, roof_bottom],
        radius=int(s * 0.05),
        fill=WHITE,
    )

    # Wheels — dark circles that are clearly visible
    wheel_r = int(s * 0.07)
    wheel_y = body_bottom - int(s * 0.01)
    for wx in [int(s * 0.30), int(s * 0.70)]:
        # Outer wheel (dark)
        draw.ellipse(
            [wx - wheel_r, wheel_y - wheel_r, wx + wheel_r, wheel_y + wheel_r],
            fill=DARK,
        )
        # Inner hub (lighter)
        hub_r = int(s * 0.03)
        draw.ellipse(
            [wx - hub_r, wheel_y - hub_r, wx + hub_r, wheel_y + hub_r],
            fill=GREEN,
        )

    # Lightning bolt — chargenode_flash style
    # The SVG path has: top point slopes down-left to a wide mid-shelf,
    # then the right edge drops to a bottom point sloping up-right to a mid-shelf.
    # Normalized from the SVG (400x794) and scaled/centered in the icon.
    bolt_h = s * 0.72  # bolt height
    bolt_w = s * 0.30  # bolt width
    bx = int(s * 0.35)  # left edge of bolt bbox
    by = int(s * 0.14)  # top edge of bolt bbox

    def bp(xf, yf):
        return (bx + int(bolt_w * xf), by + int(bolt_h * yf))

    bolt_points = [
        bp(0.53, 0.00),  # top point (slightly right of center)
        bp(0.00, 0.53),  # left end of mid-shelf
        bp(0.44, 0.53),  # right end of mid-shelf (where bottom half starts)
        bp(0.47, 0.47),  # bottom-left of top half (notch)
        bp(0.00, 0.53),  # (overlap cleaned below)
    ]
    # Simpler: follow the SVG shape faithfully
    bolt_points = [
        bp(0.53, 0.00),  # top peak
        bp(0.00, 0.53),  # mid-shelf left
        bp(0.44, 0.53),  # mid-shelf right
        bp(0.47, 1.00),  # bottom peak
        bp(1.00, 0.46),  # mid-shelf right (upper)
        bp(0.56, 0.46),  # mid-shelf left (upper)
    ]
    draw.polygon(bolt_points, fill=(255, 220, 30), outline=(220, 180, 0),
                 width=max(1, s // 128))

    return img


if __name__ == "__main__":
    for name, sz in [("icon.png", 256), ("icon@2x.png", 512)]:
        icon = draw_icon(sz)
        path = DEST / name
        icon.save(path, "PNG")
        print(f"Saved {path} ({sz}x{sz})")
