import math
import threading
import objc
from AppKit import (
    NSView, NSPanel, NSColor, NSBezierPath, NSScreen, NSFont,
    NSFontAttributeName, NSForegroundColorAttributeName, NSKernAttributeName,
    NSFontWeightLight, NSFontDescriptorSystemDesignRounded, NSLineCapStyleRound,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSAnimationContext,
    NSInsetRect, NSViewLayerContentsRedrawDuringViewResize,
)
from Foundation import NSMakeRect, NSMakePoint, NSAttributedString, NSTimer
from Quartz import CAMediaTimingFunction
from PyObjCTools import AppHelper

W, H = 90, 28
R = H / 2       # corner radius = perfect circle when the pill is H wide
PAD = 16        # side / bottom margin around the pill
LABEL_PAD = 18  # extra top margin for the "translate" label
MARGIN = 145
FPS = 1.0 / 60.0

PANEL_W = W + 2 * PAD
PANEL_H = H + PAD + LABEL_PAD

# Animation durations (seconds). Calm ease, no overshoot.
EXPAND_IN = 0.32
EXPAND_OUT = 0.22
ALPHA_IN = 0.18

_EASE = None

# One component, one look. Dictate and translate are the SAME dark pill;
# translate only adds a thin "translate" label above it. The fill is a flat,
# semi-transparent dark color (static — no blur, no adaptation), so the light
# content always reads on it. Error keeps the dark fill and a coral glyph.
FILL_RGBA = (0.13, 0.13, 0.14, 1.0)    # Dark pill fill (fully opaque)
EDGE_RGBA = (1.0, 1.0, 1.0, 0.16)      # Soft light hairline rim
BAR_RGBA = (1.0, 1.0, 1.0, 0.86)       # Bars / spinner
BORDER_W = 1.0

# "translate" label — small, soft rounded type, in the bars/spinner color.
LABEL_TEXT = "translate"
LABEL_SIZE = 8.0
LABEL_TRACKING = 0.6       # Slight letter spacing for an airy, minimal look
LABEL_RGBA = BAR_RGBA

FILL = None
EDGE = None
BAR_COLOR = None           # Recording bars / loading arc
ERROR_BAR = None           # Error "!"
LABEL_ATTRS = None
CLEAR = None


def _init_colors():
    global FILL, EDGE, BAR_COLOR, ERROR_BAR, LABEL_ATTRS, CLEAR, _EASE
    if BAR_COLOR is None:
        c = NSColor.colorWithRed_green_blue_alpha_

        FILL = c(*FILL_RGBA)
        EDGE = c(*EDGE_RGBA)
        BAR_COLOR = c(*BAR_RGBA)
        ERROR_BAR = c(236 / 255, 112 / 255, 102 / 255, 1.0)

        base = NSFont.systemFontOfSize_weight_(LABEL_SIZE, NSFontWeightLight)
        rounded = base.fontDescriptor().fontDescriptorWithDesign_(NSFontDescriptorSystemDesignRounded)
        label_font = NSFont.fontWithDescriptor_size_(rounded, LABEL_SIZE) or base
        LABEL_ATTRS = {
            NSFontAttributeName: label_font,
            NSForegroundColorAttributeName: c(*LABEL_RGBA),
            NSKernAttributeName: LABEL_TRACKING,
        }

        CLEAR = NSColor.clearColor()
        _EASE = CAMediaTimingFunction.functionWithControlPoints____(0.4, 0.0, 0.2, 1.0)


def _full_frame():
    return NSMakeRect(PAD, PAD, W, H)


def _circle_frame():
    return NSMakeRect(PAD + (W - H) / 2.0, PAD, H, H)


class PillView(NSView):
    """
    The pill body: a flat dark fill plus a thin light hairline rim, drawn
    together. Animates its frame with the expand/collapse, redrawing on resize.
    Fully static — no blur or backdrop adaptation.
    """

    def drawRect_(self, rect):
        b = self.bounds()
        r = b.size.height / 2.0
        FILL.setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(b, r, r).fill()

        # Stroke centered on a path inset by half the line width, so the rim's
        # outer edge lands on the pill edge.
        half = BORDER_W / 2.0
        inset = NSInsetRect(b, half, half)
        ir = inset.size.height / 2.0
        rim = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(inset, ir, ir)
        rim.setLineWidth_(BORDER_W)
        EDGE.setStroke()
        rim.stroke()


class GlyphView(NSView):
    """
    The animated glyph (bars / spinner / error) and the "translate" label, in a
    transparent sibling spanning the whole panel above the pill. The 60fps
    timer drives it via setNeedsDisplay.
    """

    def drawRect_(self, rect):
        self._owner._draw_overlay()


class OverlayView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(OverlayView, self).initWithFrame_(frame)
        if self is not None:
            self._mode = None
            self._translate = False
            self._phase = 0.0
            _init_colors()
            self.setWantsLayer_(True)

            surface = PillView.alloc().initWithFrame_(_circle_frame())
            surface.setWantsLayer_(True)
            surface.setLayerContentsRedrawPolicy_(NSViewLayerContentsRedrawDuringViewResize)
            self.addSubview_(surface)
            self._surface = surface

            # Glyph + label sibling — full panel, animated by the timer.
            glyph = GlyphView.alloc().initWithFrame_(self.bounds())
            glyph._owner = self
            glyph.setWantsLayer_(True)
            self.addSubview_(glyph)
            self._glyph = glyph
        return self

    def setMode_(self, mode):
        if self._mode != mode:
            self._mode = mode
            self._phase = 0.0
            self._glyph.setNeedsDisplay_(True)

    def setTranslate_(self, translate):
        if self._translate != translate:
            self._translate = translate
            self._glyph.setNeedsDisplay_(True)

    def expand(self):
        # Calm ease, no overshoot — the pill settles statically.
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(EXPAND_IN)
        ctx.setTimingFunction_(_EASE)
        ctx.setAllowsImplicitAnimation_(True)
        self._surface.animator().setFrame_(_full_frame())
        NSAnimationContext.endGrouping()

    def collapse(self):
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(EXPAND_OUT)
        ctx.setTimingFunction_(_EASE)
        ctx.setAllowsImplicitAnimation_(True)
        self._surface.animator().setFrame_(_circle_frame())
        NSAnimationContext.endGrouping()

    def tick_(self, timer):
        if self._mode == "recording":
            self._phase += 0.1
            self._glyph.setNeedsDisplay_(True)
        elif self._mode == "loading":
            self._phase += 4.0
            self._glyph.setNeedsDisplay_(True)

    def _draw_overlay(self):
        # The glyph layer spans the whole panel; the pill occupies _full_frame,
        # so the glyph is drawn in pill-local coordinates and the label sits in
        # the margin above it.
        if self._translate and self._mode != "error":
            s = NSAttributedString.alloc().initWithString_attributes_(LABEL_TEXT, LABEL_ATTRS)
            sz = s.size()
            x = (PANEL_W - sz.width) / 2.0
            y = PAD + H + (LABEL_PAD - sz.height) / 2.0
            s.drawAtPoint_(NSMakePoint(x, y))

        cx, cy = PAD + W / 2.0, PAD + H / 2.0

        if self._mode == "error":
            # "!" — vertical bar + dot
            ERROR_BAR.setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(cx - 1, cy - 4, 2, 10), 1, 1
            ).fill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(cx - 1, cy - 8, 2, 2), 1, 1
            ).fill()

        elif self._mode == "recording":
            # Center-weighted envelope reads like a real voice meter.
            env = (0.55, 0.8, 1.0, 0.8, 0.55)
            barW, gap = 2.0, 3.5
            total = 5 * barW + 4 * gap
            x0 = cx - total / 2.0
            BAR_COLOR.setFill()
            for i in range(5):
                t = math.sin(self._phase + i * 1.2) * 0.5 + 0.5
                h = 5 + t * 11 * env[i]
                y = cy - h / 2.0
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(x0 + i * (barW + gap), y, barW, h), 1, 1
                ).fill()

        elif self._mode == "loading":
            # A single clean arc, round caps, no background track — a calm,
            # minimal spinner.
            BAR_COLOR.setStroke()
            arc = NSBezierPath.bezierPath()
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                NSMakePoint(cx, cy), 7.5, self._phase, self._phase + 270, False
            )
            arc.setLineWidth_(2.0)
            arc.setLineCapStyle_(NSLineCapStyleRound)
            arc.stroke()


class Overlay:
    def __init__(self):
        self._panel = None
        self._view = None
        self._timer = None
        self._hiding = False
        # Bumped on every _show. The error-flash timer captures the value at
        # flash time, so a flash can never hide a cycle that started after it.
        self._gen = 0

    def show(self, mode, translate=False):
        AppHelper.callAfter(self._show, mode, translate)

    def flash_error(self, duration=1.2):
        AppHelper.callAfter(self._flash_error, duration)

    def hide(self):
        AppHelper.callAfter(self._hide)

    def _flash_error(self, duration):
        self._show("error", False)
        gen = self._gen
        threading.Timer(
            duration, lambda: AppHelper.callAfter(self._hide_if_current, gen)
        ).start()

    def _hide_if_current(self, gen):
        if gen == self._gen:
            self._hide()

    def _center(self):
        # Bottom-left of the pill on screen (the panel is inset around it).
        sf = NSScreen.mainScreen().frame()
        x = sf.origin.x + (sf.size.width - W) / 2
        y = sf.origin.y + MARGIN - H
        return x, y

    def _ensure_panel(self):
        # Build the panel once and keep it alive (hidden at alpha 0) between
        # cycles — no per-cycle teardown/recreate.
        if self._panel is not None:
            return
        x, y = self._center()
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x - PAD, y - PAD, PANEL_W, PANEL_H),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(1000)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(CLEAR)
        panel.setHasShadow_(False)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setFloatingPanel_(True)
        panel.setAlphaValue_(0.0)

        view = OverlayView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_W, PANEL_H))
        panel.setContentView_(view)
        panel.orderFrontRegardless()

        self._panel = panel
        self._view = view

    def _show(self, mode, translate):
        _init_colors()
        self._ensure_panel()
        self._hiding = False
        self._gen += 1

        x, y = self._center()
        self._panel.setFrameOrigin_(NSMakePoint(x - PAD, y - PAD))
        self._view.setTranslate_(translate)
        self._view.setMode_(mode)

        # The redraw timer runs only while the pill is visible.
        if self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                FPS, self._view, b"tick:", None, True
            )

        # Fade the window in (re-targeted through the animator so an in-flight
        # fade-out can't keep driving it toward 0); expand the pill.
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(ALPHA_IN)
        self._panel.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()

        self._view.expand()

    def _hide(self):
        if not self._panel or self._hiding:
            return
        self._hiding = True

        self._view.collapse()

        # Fade out over the same span the pill collapses. The panel is kept
        # alive (not torn down).
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(EXPAND_OUT)
        ctx.setCompletionHandler_(self._on_hide_done)
        self._panel.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()

    def _on_hide_done(self):
        if self._hiding and self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        self._hiding = False
