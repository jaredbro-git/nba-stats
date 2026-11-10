"""The iPhone app icon: the Mac icon's basketball on a full-bleed navy square (iOS rounds the corners itself).

Usage (from the project folder): .venv-build/bin/python ios/Tools/make_icon.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "build_tools"))
import make_icon  # noqa: E402

make_icon.TILE = (0, 0, make_icon.SIZE, make_icon.SIZE)
make_icon.RADIUS = 0
icon = make_icon.draw().convert("RGB")  # no transparency in iOS icons
out = Path(__file__).resolve().parents[1] / "NBAStats/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png"
icon.save(out)
print("Wrote", out)
