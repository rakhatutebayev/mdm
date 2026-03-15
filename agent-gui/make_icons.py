from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), "#0f172a")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 232, 232), radius=48, fill="#2563eb")
    draw.rounded_rectangle((56, 56, 200, 200), radius=32, fill="#0f172a")
    draw.text((82, 82), "N", fill="#e2e8f0")
    image.save(ASSETS / "nocko-agent.png")
    image.save(ASSETS / "nocko-agent.ico", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])


if __name__ == "__main__":
    main()
