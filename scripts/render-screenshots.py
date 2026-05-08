#!/usr/bin/env python3
"""
Render the OpenSpeaksy recording-overlay state to PNG for the README.
Bars are scaled in proportion to the pill — running OverlayView.drawRect_
directly leaves bar widths/heights at their original 2 px which looks tiny
on a 4× retina-style render.

Run from repo root after install:
    venv/bin/python scripts/render-screenshots.py
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory,
    NSView, NSColor, NSBezierPath, NSBitmapImageFileTypePNG,
)
from Foundation import NSMakeRect

app = NSApplication.sharedApplication()
app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


SCALE = 4
W = 90 * SCALE
H = 28 * SCALE
PAD = 12 * SCALE
R = H / 2

BAR_COLOR = NSColor.colorWithRed_green_blue_alpha_(56 / 255, 189 / 255, 248 / 255, 1.0)
BG_COLOR = NSColor.colorWithRed_green_blue_alpha_(15 / 255, 23 / 255, 42 / 255, 0.92)


class RecordingPillView(NSView):
    def isOpaque(self):
        return False

    def drawRect_(self, rect):
        bounds = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(PAD, PAD, W, H), R, R
        )
        BG_COLOR.setFill()
        path.fill()

        # Bars scale with SCALE so the relative density matches the live overlay.
        barW = 2.0 * SCALE
        gap = 3.5 * SCALE
        total = 5 * barW + 4 * gap
        x0 = PAD + (W - total) / 2
        cy = PAD + H / 2
        # Pick a phase that shows varied heights (mid-swing of the sine wave).
        phase = 1.6
        BAR_COLOR.setFill()
        for i in range(5):
            t = math.sin(phase + i * 1.2) * 0.5 + 0.5
            h = (4 + t * 12) * SCALE
            y = cy - h / 2
            bp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x0 + i * (barW + gap), y, barW, h), 1 * SCALE, 1 * SCALE
            )
            bp.fill()


OUT_DIR = ROOT / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

view = RecordingPillView.alloc().initWithFrame_(NSMakeRect(0, 0, W + 2 * PAD, H + 2 * PAD))
view.setWantsLayer_(True)

bitmap = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)

out_path = OUT_DIR / "recording.png"
data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
data.writeToFile_atomically_(str(out_path), True)
print(f"wrote {out_path.relative_to(ROOT)}")
