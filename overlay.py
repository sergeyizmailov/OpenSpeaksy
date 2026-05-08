import math
import threading
import objc
from AppKit import (
    NSView, NSPanel, NSColor, NSBezierPath, NSScreen,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSAnimationContext,
)
from Foundation import NSMakeRect, NSMakePoint, NSTimer
from PyObjCTools import AppHelper

W, H = 90, 28
R = H / 2       # corner radius = perfect circle when panel is H×H
MARGIN = 145
FPS = 1.0 / 60.0

BAR_COLOR = None
BAR_DIM = None
BG_COLOR = None
BG_ERROR = None
ERROR_BAR = None
CLEAR = None


def _init_colors():
    global BAR_COLOR, BAR_DIM, BG_COLOR, BG_ERROR, ERROR_BAR, CLEAR
    if BAR_COLOR is None:
        BAR_COLOR = NSColor.colorWithRed_green_blue_alpha_(56 / 255, 189 / 255, 248 / 255, 1.0)
        BAR_DIM  = NSColor.colorWithRed_green_blue_alpha_(56 / 255, 189 / 255, 248 / 255, 0.2)
        BG_COLOR = NSColor.colorWithRed_green_blue_alpha_(15 / 255, 23 / 255, 42 / 255, 0.92)
        BG_ERROR = NSColor.colorWithRed_green_blue_alpha_(80 / 255, 15 / 255, 20 / 255, 0.95)
        ERROR_BAR = NSColor.colorWithRed_green_blue_alpha_(248 / 255, 113 / 255, 113 / 255, 1.0)
        CLEAR    = NSColor.clearColor()


class OverlayView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(OverlayView, self).initWithFrame_(frame)
        if self is not None:
            self._mode = None
            self._phase = 0.0
            self.setWantsLayer_(True)
        return self

    def setMode_(self, mode):
        if self._mode != mode:
            self._mode = mode
            self._phase = 0.0

    def tick_(self, timer):
        if self._mode == "recording":
            self._phase += 0.1
        elif self._mode == "loading":
            self._phase += 6.0
        self.setNeedsDisplay_(True)

    def isOpaque(self):
        return False

    def drawRect_(self, rect):
        _init_colors()
        bounds = self.bounds()

        # Pill shape — R stays constant so small panel = circle, full panel = pill
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, R, R)
        if self._mode == "error":
            BG_ERROR.setFill()
        else:
            BG_COLOR.setFill()
        path.fill()

        if self._mode == "error":
            # "!" — vertical bar + dot
            cx = bounds.size.width / 2
            cy = bounds.size.height / 2
            ERROR_BAR.setFill()
            bar = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(cx - 1, cy - 4, 2, 10), 1, 1
            )
            bar.fill()
            dot = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(cx - 1, cy - 8, 2, 2), 1, 1
            )
            dot.fill()
        elif self._mode == "recording":
            barW, gap = 2.0, 3.5
            total = 5 * barW + 4 * gap
            x0 = (bounds.size.width - total) / 2
            BAR_COLOR.setFill()
            for i in range(5):
                t = math.sin(self._phase + i * 1.2) * 0.5 + 0.5
                h = 4 + t * 12
                y = (bounds.size.height - h) / 2
                bp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(x0 + i * (barW + gap), y, barW, h), 1, 1
                )
                bp.fill()

        elif self._mode == "loading":
            cx = bounds.size.width / 2
            cy = bounds.size.height / 2
            center = NSMakePoint(cx, cy)

            BAR_DIM.setStroke()
            circle = NSBezierPath.bezierPath()
            circle.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                center, 8.0, 0, 360, False
            )
            circle.setLineWidth_(2)
            circle.stroke()

            BAR_COLOR.setStroke()
            arc = NSBezierPath.bezierPath()
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                center, 8.0, self._phase, self._phase + 90, False
            )
            arc.setLineWidth_(2)
            arc.stroke()


class Overlay:
    def __init__(self):
        self._panel = None
        self._view = None
        self._timer = None
        self._hiding = False

    def show(self, mode):
        AppHelper.callAfter(self._show, mode)

    def flash_error(self, duration=1.2):
        AppHelper.callAfter(self._flash_error, duration)

    def hide(self):
        AppHelper.callAfter(self._hide)

    def _flash_error(self, duration):
        self._show("error")
        threading.Timer(duration, lambda: AppHelper.callAfter(self._hide)).start()

    def _center(self):
        sf = NSScreen.mainScreen().frame()
        x = sf.origin.x + (sf.size.width - W) / 2
        y = sf.origin.y + MARGIN - H
        return x, y

    def _show(self, mode):
        _init_colors()
        self._hiding = False

        if self._panel:
            # Already visible — cancel any hide animation, switch mode
            self._panel.setAlphaValue_(1.0)
            x, y = self._center()
            self._panel.setFrame_display_(NSMakeRect(x, y, W, H), True)
            if self._view:
                self._view.setMode_(mode)
            return

        self._destroy()
        x, y = self._center()

        # Start as circle: H×H centered on where the pill will be
        sx = x + (W - H) / 2

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(sx, y, H, H),
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

        view = OverlayView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        view.setMode_(mode)
        panel.setContentView_(view)
        panel.orderFrontRegardless()

        # Appear instantly as dot, then expand to pill
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(0.0)
        panel.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()

        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(0.28)
        panel.animator().setFrame_display_(NSMakeRect(x, y, W, H), True)
        NSAnimationContext.endGrouping()

        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            FPS, view, b"tick:", None, True
        )
        self._panel = panel
        self._view = view

    def _hide(self):
        if not self._panel or self._hiding:
            return
        self._hiding = True

        x, y = self._center()
        sx = x + (W - H) / 2

        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(0.22)
        ctx.setCompletionHandler_(self._on_hide_done)
        self._panel.animator().setAlphaValue_(0.0)
        self._panel.animator().setFrame_display_(NSMakeRect(sx, y, H, H), True)
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
