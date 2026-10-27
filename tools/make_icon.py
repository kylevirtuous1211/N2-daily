"""Render static/icon.svg to assets/n2daily.ico with headless Chrome (PNG-compressed ICO entries)."""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
SIZES = (16, 24, 32, 48, 64, 256)
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def render_png(svg: str, size: int, workdir: Path) -> bytes:
    page = workdir / f"icon{size}.html"
    page.write_text(
        f"<html><body style='margin:0;background:transparent'>"
        f"<div style='width:{size}px;height:{size}px'>{svg.replace('<svg ', f'<svg width=\"{size}\" height=\"{size}\" ', 1)}</div>"
        f"</body></html>",
        encoding="utf-8",
    )
    output = workdir / f"icon{size}.png"
    subprocess.run(
        [str(CHROME), "--headless", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000",
         f"--screenshot={output}", f"--window-size={size},{size}", page.as_uri()],
        check=True, capture_output=True, timeout=60,
    )
    return output.read_bytes()


def build_ico(images: dict[int, bytes]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, png in images.items():
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    return header + entries + payload


def main() -> int:
    svg = (APP_DIR / "static" / "icon.svg").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as directory:
        images = {size: render_png(svg, size, Path(directory)) for size in SIZES}
    target = APP_DIR / "assets" / "n2daily.ico"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(build_ico(images))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
