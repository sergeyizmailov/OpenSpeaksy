#!/usr/bin/env python3
"""
Render the OpenSpeaksy overlay in each mode to PNG files for the README.
Uses NSBitmapImageRep — no Screen Recording permission required, no live UI.

Run from repo root after install:
    venv/bin/python scripts/render-screenshots.py
"""
import sys
from pathlib import Path

# Add project root to path so we can import overlay
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory,
    NSView, NSBitmapImageFileTypePNG,
)
from Foundation import NSMakeRect

# AppKit must be initialized before we can render
app = NSApplication.sharedApplication()
app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

import overlay
from overlay import OverlayView

SCALE = 4
PAD = 12 * SCALE
W = 90 * SCALE
H = 28 * SCALE

# Patch overlay constants so the pill draws at SCALE×
overlay.W = W
overlay.H = H
overlay.R = H / 2

OUT_DIR = ROOT / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

for mode in ("recording", "loading", "error"):
    view = OverlayView.alloc().initWithFrame_(NSMakeRect(PAD, PAD, W, H))
    view.setMode_(mode)

    container = NSView.alloc().initWithFrame_(
        NSMakeRect(0, 0, W + 2 * PAD, H + 2 * PAD)
    )
    container.setWantsLayer_(True)
    container.addSubview_(view)

    bitmap = container.bitmapImageRepForCachingDisplayInRect_(container.bounds())
    container.cacheDisplayInRect_toBitmapImageRep_(container.bounds(), bitmap)

    out_path = OUT_DIR / f"{mode}.png"
    data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    data.writeToFile_atomically_(str(out_path), True)
    print(f"wrote {out_path.relative_to(ROOT)}")
