import math
import threading
import objc
from AppKit import (
    NSView, NSPanel, NSColor, NSBezierPath, NSScreen, NSGraphicsContext,
    NSLineCapStyleRound,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSAnimationContext,
)
from Foundation import NSMakeRect, NSMakePoint, NSTimer
from Quartz import (
    CAGradientLayer, CALayer, CATransaction, CAMediaTimingFunction,
    CASpringAnimation, CABasicAnimation,
)
from PyObjCTools import AppHelper

W, H = 90, 28
R = H / 2       # corner radius = perfect circle when the pill layer is H wide
PAD = 16        # transparent margin so the spring overshoot isn't clipped by the window
MARGIN = 145
FPS = 1.0 / 60.0

PANEL_W = W + 2 * PAD
PANEL_H = H + 2 * PAD

# The pill grows/shrinks via Core Animation on the layer (GPU/render thread),
# so it stays smooth regardless of main-thread load. The timer only redraws the
# small glyph during recording/loading. Durations are seconds.
EXPAND_OUT = 0.22
ALPHA_IN = 0.18
GLYPH_FADE = 0.24

# Material-style easing — gentle in, brisk settle (used for collapse/fades).
_EASE = None

# Monochrome system. Dictate and translate are the SAME component in two themes —
# identical alpha, gradient lift, hairline strength and contrast — only the
# surface (dark vs light) and the inverted glyph differ. They're derived from one
# shared recipe below so the two stay mirror-consistent.
#   dictate   = dark graphite pill, near-white glyph
#   translate = light silver pill,  graphite glyph
# Error keeps a single restrained semantic accent (muted coral) — an alert must
# stay noticeable; everything else is neutral.
PILL_ALPHA = 0.95          # Pill background opacity (both themes)
GRAD_LIFT = 16 / 255       # Top of the gradient is this much lighter than bottom
EDGE_ALPHA = 0.10          # Hairline rim strength (both themes)
DIM_ALPHA = 0.17           # Loading-track / accent dim level (both themes)

BAR_COLOR = None           # Glyph/accent on the dark pill
BAR_DIM = None
TRANSLATE_BAR = None       # Glyph/accent on the light pill
TRANSLATE_BAR_DIM = None
D_TOP = D_BOT = None       # Dark graphite pill (dictate)
T_TOP = T_BOT = None       # Silver pill (translate)
E_TOP = E_BOT = None       # Error pill
ERROR_BAR = None
EDGE_DARK = None           # Hairline edge for dark pills (subtle light rim)
EDGE_LIGHT = None          # Hairline edge for the light pill (subtle dark rim)
CLEAR = None


def _init_colors():
    global BAR_COLOR, BAR_DIM, TRANSLATE_BAR, TRANSLATE_BAR_DIM
    global D_TOP, D_BOT, T_TOP, T_BOT, E_TOP, E_BOT
    global ERROR_BAR, EDGE_DARK, EDGE_LIGHT, CLEAR, _EASE
    if BAR_COLOR is None:
        c = NSColor.colorWithRed_green_blue_alpha_

        def gradient(base):
            bot = c(base, base, base, PILL_ALPHA)
            top = c(base + GRAD_LIFT, base + GRAD_LIFT, base + GRAD_LIFT, PILL_ALPHA)
            return top, bot

        # Dark theme (dictate): dark surface, near-white glyph.
        D_TOP, D_BOT = gradient(22 / 255)
        BAR_COLOR = c(246 / 255, 247 / 255, 250 / 255, 1.0)
        BAR_DIM = c(246 / 255, 247 / 255, 250 / 255, DIM_ALPHA)
        EDGE_DARK = c(1.0, 1.0, 1.0, EDGE_ALPHA)

        # Light theme (translate): mirror of the above — light surface, graphite glyph.
        T_TOP, T_BOT = gradient(232 / 255)
        TRANSLATE_BAR = c(40 / 255, 40 / 255, 44 / 255, 1.0)
        TRANSLATE_BAR_DIM = c(40 / 255, 40 / 255, 44 / 255, DIM_ALPHA)
        EDGE_LIGHT = c(0.0, 0.0, 0.0, EDGE_ALPHA)

        # Error keeps its own dark surface + coral glyph.
        E_TOP = c(44 / 255, 32 / 255, 32 / 255, 0.96)
        E_BOT = c(24 / 255, 19 / 255, 19 / 255, 0.96)
        ERROR_BAR = c(236 / 255, 112 / 255, 102 / 255, 1.0)

        CLEAR = NSColor.clearColor()
        _EASE = CAMediaTimingFunction.functionWithControlPoints____(0.4, 0.0, 0.2, 1.0)


def _full_frame():
    return NSMakeRect(PAD, PAD, W, H)


def _circle_frame():
    return NSMakeRect(PAD + (W - H) / 2.0, PAD, H, H)


class OverlayView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(OverlayView, self).initWithFrame_(frame)
        if self is not None:
            self._mode = None
            self._translate = False
            self._phase = 0.0
            _init_colors()

            # Layer-hosting: AppKit won't call drawRect; we composite a gradient
            # pill (animated, with a hairline rim) behind a delegate-drawn glyph.
            scale = NSScreen.mainScreen().backingScaleFactor()
            root = CALayer.layer()
            root.setMasksToBounds_(False)
            self.setLayer_(root)
            self.setWantsLayer_(True)

            self._pill = CAGradientLayer.layer()
            self._pill.setStartPoint_(NSMakePoint(0.5, 1.0))   # top → bottom
            self._pill.setEndPoint_(NSMakePoint(0.5, 0.0))
            self._pill.setCornerRadius_(R)
            self._pill.setBorderWidth_(1.0)
            self._pill.setContentsScale_(scale)
            self._pill.setFrame_(_circle_frame())
            root.addSublayer_(self._pill)

            self._glyph = CALayer.layer()
            self._glyph.setFrame_(_full_frame())
            self._glyph.setContentsScale_(scale)
            self._glyph.setDelegate_(self)
            root.addSublayer_(self._glyph)

            self._apply_colors()
        return self

    def setMode_(self, mode):
        if self._mode != mode:
            self._mode = mode
            self._phase = 0.0
            self._apply_colors()
            self._glyph.setNeedsDisplay()

    def setTranslate_(self, translate):
        if self._translate != translate:
            self._translate = translate
            self._apply_colors()
            self._glyph.setNeedsDisplay()

    def _apply_colors(self):
        if self._mode == "error":
            top, bot, edge = E_TOP, E_BOT, EDGE_DARK
        elif self._translate:
            top, bot, edge = T_TOP, T_BOT, EDGE_LIGHT
        else:
            top, bot, edge = D_TOP, D_BOT, EDGE_DARK
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self._pill.setColors_([top.CGColor(), bot.CGColor()])
        self._pill.setBorderColor_(edge.CGColor())
        CATransaction.commit()

    def expand(self):
        # Spring gives a natural, lively settle on appear. Only the width changes
        # (the pill stays centered), so we animate bounds.size.width alone.
        from_w = self._pill.bounds().size.width
        target = _full_frame()
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self._pill.setFrame_(target)
        CATransaction.commit()
        spring = CASpringAnimation.animationWithKeyPath_("bounds.size.width")
        spring.setFromValue_(from_w)
        spring.setToValue_(target.size.width)
        spring.setMass_(1.0)
        spring.setStiffness_(320.0)
        spring.setDamping_(30.0)
        spring.setInitialVelocity_(0.0)
        spring.setDuration_(spring.settlingDuration())
        self._pill.addAnimation_forKey_(spring, "expand")

    def collapse(self):
        CATransaction.begin()
        CATransaction.setAnimationDuration_(EXPAND_OUT)
        CATransaction.setAnimationTimingFunction_(_EASE)
        self._pill.setFrame_(_circle_frame())
        CATransaction.commit()

    def fadeGlyphIn(self):
        anim = CABasicAnimation.animationWithKeyPath_("opacity")
        anim.setFromValue_(0.0)
        anim.setToValue_(1.0)
        anim.setDuration_(GLYPH_FADE)
        anim.setTimingFunction_(_EASE)
        self._glyph.addAnimation_forKey_(anim, "fadein")

    def tick_(self, timer):
        if self._mode == "recording":
            self._phase += 0.1
            self._glyph.setNeedsDisplay()
        elif self._mode == "loading":
            self._phase += 6.0
            self._glyph.setNeedsDisplay()

    def drawLayer_inContext_(self, layer, ctx):
        gc = NSGraphicsContext.graphicsContextWithCGContext_flipped_(ctx, False)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.setCurrentContext_(gc)
        try:
            self._draw_glyph()
        finally:
            NSGraphicsContext.restoreGraphicsState()

    def _draw_glyph(self):
        bar_color = TRANSLATE_BAR if self._translate else BAR_COLOR
        bar_dim = TRANSLATE_BAR_DIM if self._translate else BAR_DIM
        cx, cy = W / 2.0, H / 2.0

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
            x0 = (W - total) / 2
            bar_color.setFill()
            for i in range(5):
                t = math.sin(self._phase + i * 1.2) * 0.5 + 0.5
                h = 5 + t * 11 * env[i]
                y = (H - h) / 2
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(x0 + i * (barW + gap), y, barW, h), 1, 1
                ).fill()

        elif self._mode == "loading":
            center = NSMakePoint(cx, cy)
            bar_dim.setStroke()
            track = NSBezierPath.bezierPath()
            track.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                center, 8.0, 0, 360, False
            )
            track.setLineWidth_(2.0)
            track.stroke()

            bar_color.setStroke()
            arc = NSBezierPath.bezierPath()
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                center, 8.0, self._phase, self._phase + 100, False
            )
            arc.setLineWidth_(2.2)
            arc.setLineCapStyle_(NSLineCapStyleRound)
            arc.stroke()


class Overlay:
    def __init__(self):
        self._panel = None
        self._view = None
        self._timer = None
        self._hiding = False

    def show(self, mode, translate=False):
        AppHelper.callAfter(self._show, mode, translate)

    def flash_error(self, duration=1.2):
        AppHelper.callAfter(self._flash_error, duration)

    def hide(self):
        AppHelper.callAfter(self._hide)

    def _flash_error(self, duration):
        # Error keeps its red background regardless of cycle intent —
        # translate flag is irrelevant for the error glyph.
        self._show("error", False)
        threading.Timer(duration, lambda: AppHelper.callAfter(self._hide)).start()

    def _center(self):
        # Bottom-left of the pill on screen (the panel is inset by PAD around it).
        sf = NSScreen.mainScreen().frame()
        x = sf.origin.x + (sf.size.width - W) / 2
        y = sf.origin.y + MARGIN - H
        return x, y

    def _show(self, mode, translate):
        _init_colors()
        self._hiding = False

        if self._panel:
            # Already visible — cancel any hide animation, switch mode, re-expand.
            self._panel.setAlphaValue_(1.0)
            x, y = self._center()
            self._panel.setFrameOrigin_(NSMakePoint(x - PAD, y - PAD))
            if self._view:
                self._view.setTranslate_(translate)
                self._view.setMode_(mode)
                self._view.expand()
            return

        self._destroy()
        x, y = self._center()

        # Panel is the pill plus a transparent PAD margin (spring-overshoot headroom);
        # the pill layer is what animates, so the window frame is never resized.
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
        view.setTranslate_(translate)
        view.setMode_(mode)
        panel.setContentView_(view)
        panel.orderFrontRegardless()

        # Fade in via GPU opacity; spring the pill open; ease the glyph in.
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(ALPHA_IN)
        panel.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()

        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            FPS, view, b"tick:", None, True
        )
        self._panel = panel
        self._view = view

        view.expand()
        view.fadeGlyphIn()

    def _hide(self):
        if not self._panel or self._hiding:
            return
        self._hiding = True

        if self._view:
            self._view.collapse()

        # Fade out over the same span the pill collapses, then tear down.
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(EXPAND_OUT)
        ctx.setCompletionHandler_(self._on_hide_done)
        self._panel.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()

    def _on_hide_done(self):
        if self._hiding:
            self._destroy()
        self._hiding = False

    def _destroy(self):
        if self._timer:
            self._timer.invalidate()
            self._timer = None
        if self._panel:
            self._panel.orderOut_(None)
            self._panel = None
        self._view = None
