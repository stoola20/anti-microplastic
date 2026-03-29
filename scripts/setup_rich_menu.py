#!/usr/bin/env python3
"""Generate Rich Menu image and register it with LINE via Messaging API.

Usage:
    python scripts/setup_rich_menu.py

Requires LINE_CHANNEL_ACCESS_TOKEN in environment (or .env file).
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

import httpx
from PIL import Image, ImageDraw, ImageFont

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# Rich Menu image dimensions (half-size)
WIDTH = 2500
HEIGHT = 843
HALF_W = WIDTH // 2

# Colors
GREEN_START = (67, 160, 71)    # #43A047
GREEN_END = (46, 125, 50)      # #2E7D32
BLUE_START = (30, 136, 229)    # #1E88E5
BLUE_END = (21, 101, 192)      # #1565C0
WHITE = (255, 255, 255)

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
IMAGE_PATH = os.path.join(ASSETS_DIR, "rich_menu.png")


def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linear interpolate between two RGB colors."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _draw_gradient(img: Image.Image, x0: int, y0: int, x1: int, y1: int,
                   color_start: tuple, color_end: tuple) -> None:
    """Draw a vertical gradient on img using row-by-row line drawing."""
    draw = ImageDraw.Draw(img)
    h = y1 - y0
    for y in range(y0, y1):
        t = (y - y0) / h
        color = _lerp_color(color_start, color_end, t)
        draw.line([(x0, y), (x1, y)], fill=color)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    """Find a font that supports CJK characters."""
    candidates = [
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        # Linux
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    # Fallback to default
    return ImageFont.load_default()


def generate_image() -> str:
    """Generate the Rich Menu image and save to assets/rich_menu.png."""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    img = Image.new("RGB", (WIDTH, HEIGHT))

    # Draw gradient backgrounds
    _draw_gradient(img, 0, 0, HALF_W, HEIGHT, GREEN_START, GREEN_END)
    _draw_gradient(img, HALF_W, 0, WIDTH, HEIGHT, BLUE_START, BLUE_END)

    draw = ImageDraw.Draw(img)

    # Divider line
    draw.line([(HALF_W, 0), (HALF_W, HEIGHT)], fill=WHITE, width=3)

    # Circle parameters
    circle_radius = 72
    circle_y_center = HEIGHT // 2 - 60

    # Font sizes
    font_icon = _find_font(56)
    font_main = _find_font(52)
    font_sub = _find_font(28)

    for cx, icon_char, main_text, sub_text in [
        (HALF_W // 2, "?", "使用說明", "How to use"),
        (HALF_W + HALF_W // 2, "i", "查看詳細", "View details"),
    ]:
        # Draw circle outline
        draw.ellipse(
            [cx - circle_radius, circle_y_center - circle_radius,
             cx + circle_radius, circle_y_center + circle_radius],
            outline=WHITE, width=4,
        )
        # Draw icon character centered in circle
        bbox = draw.textbbox((0, 0), icon_char, font=font_icon)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (cx - tw // 2, circle_y_center - th // 2 - bbox[1]),
            icon_char, fill=WHITE, font=font_icon,
        )
        # Main text below circle
        main_y = circle_y_center + circle_radius + 36
        bbox = draw.textbbox((0, 0), main_text, font=font_main)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, main_y), main_text, fill=WHITE, font=font_main)
        # Sub text
        sub_y = main_y + 70
        bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
        tw = bbox[2] - bbox[0]
        draw.text(
            (cx - tw // 2, sub_y), sub_text,
            fill=(220, 220, 220), font=font_sub,
        )

    img.save(IMAGE_PATH, "PNG")
    print(f"Image saved to {IMAGE_PATH}")
    return IMAGE_PATH


def create_rich_menu() -> str:
    """Create a Rich Menu object via LINE API. Returns the richMenuId."""
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "size": {"width": 2500, "height": 843},
        "selected": True,
        "name": "EDC 分析小幫手選單",
        "chatBarText": "📋 功能選單",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 1250, "height": 843},
                "action": {"type": "postback", "data": "action=help", "displayText": "使用說明"},
            },
            {
                "bounds": {"x": 1250, "y": 0, "width": 1250, "height": 843},
                "action": {"type": "postback", "data": "action=detail", "displayText": "查看詳細"},
            },
        ],
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://api.line.me/v2/bot/richmenu",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        rich_menu_id = resp.json()["richMenuId"]
        print(f"Created Rich Menu: {rich_menu_id}")
        return rich_menu_id


def upload_image(rich_menu_id: str, image_path: str) -> None:
    """Upload the image to the Rich Menu."""
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "image/png",
    }
    with open(image_path, "rb") as f:
        data = f.read()
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            content=data,
            headers=headers,
        )
        resp.raise_for_status()
        print(f"Uploaded image to Rich Menu {rich_menu_id}")


def set_default(rich_menu_id: str) -> None:
    """Set the Rich Menu as default for all users."""
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"https://api.line.me/v2/user/all/richmenu/{rich_menu_id}",
            headers=headers,
        )
        resp.raise_for_status()
        print(f"Set Rich Menu {rich_menu_id} as default")


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("Error: LINE_CHANNEL_ACCESS_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    image_path = generate_image()
    # Note: if upload_image or set_default fails, the Rich Menu object
    # created by create_rich_menu() remains in LINE as an orphan.
    # Clean up via: DELETE https://api.line.me/v2/bot/richmenu/{richMenuId}
    rich_menu_id = create_rich_menu()
    upload_image(rich_menu_id, image_path)
    set_default(rich_menu_id)
    print("\nDone! Rich Menu is now active for all users.")


if __name__ == "__main__":
    main()
