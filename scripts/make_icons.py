from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
source = root / "assets" / "sovereign-agent-icon.png"
target = root / "frontend" / "src-tauri" / "icons"
target.mkdir(parents=True, exist_ok=True)

with Image.open(source) as image:
    icon = image.convert("RGBA")
    for size in (32, 128, 256, 512):
        icon.resize((size, size), Image.Resampling.LANCZOS).save(target / f"{size}x{size}.png")
    icon.save(target / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
