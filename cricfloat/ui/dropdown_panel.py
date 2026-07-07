"""A custom dark dropdown panel styled to match the overlay widget.

The native NSMenu can't be themed to match the dark HUD, so this is a separate
borderless floating window that appears just below the widget and lists the
matches as dark rows: LIVE / FINISHED / UPCOMING sections, India matches first
(flagged), with a hover highlight. Clicking a row selects that match.
"""

from __future__ import annotations

import warnings
from typing import Callable

import Cocoa
import objc
from Cocoa import (
    NSColor,
    NSFont,
    NSMakeRect,
    NSPoint,
    NSScrollView,
    NSTextField,
    NSView,
    NSVisualEffectView,
    NSWindow,
)

warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)

NSScreenSaverWindowLevel = 1000
NSWindowStyleMaskBorderless = 0
NSVisualEffectMaterialHUDWindow = 13
NSVisualEffectStateActive = 1
NSVisualEffectBlendingModeBehindWindow = 0

_SCRIM = (0.11, 0.12, 0.14)
_LIVE = (0.30, 0.75, 0.47)

_ROW_H = 26.0
_HDR_H = 20.0
_PAD = 6.0
_WIDTH = 280.0  # matches the widget width so the panel overlays it cleanly
_MAX_H = 420.0  # cap the panel; scroll beyond this


def _white(a: float):
    return NSColor.colorWithCalibratedWhite_alpha_(1.0, a)


def _rgb(rgb, a: float = 1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], a)


class FlippedView(NSView):
    """A view with a top-left origin, so scroll content lays out top-down and
    scrolling starts at the top."""

    def isFlipped(self):  # noqa: N802
        return True


class RowView(NSView):
    """One selectable match row: hover highlights it, click selects it."""

    def initWithFrame_matchId_onSelect_(self, frame, match_id, on_select):  # noqa: N802
        self = objc.super(RowView, self).initWithFrame_(frame)
        if self is not None:
            self._match_id = match_id
            self._on_select = on_select
            self.setWantsLayer_(True)
            self.layer().setCornerRadius_(6.0)
            self._add_tracking()
        return self

    def _add_tracking(self):
        # Track mouse enter/exit for the hover highlight. Options: MouseEnteredAndExited
        # (0x01) | ActiveAlways (0x80) | InVisibleRect (0x200) so it follows resizes.
        opts = 0x01 | 0x80 | 0x200
        area = Cocoa.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), opts, self, None)
        self.addTrackingArea_(area)

    def mouseEntered_(self, event):  # noqa: N802
        self.layer().setBackgroundColor_(_white(0.10).CGColor())

    def mouseExited_(self, event):  # noqa: N802
        self.layer().setBackgroundColor_(NSColor.clearColor().CGColor())

    def mouseUp_(self, event):  # noqa: N802
        # Flash the row (a brief green highlight) so the click is visibly
        # acknowledged, then fire selection just after so the highlight shows
        # before the panel closes.
        self.layer().setBackgroundColor_(_rgb(_LIVE, 0.55).CGColor())
        self.performSelector_withObject_afterDelay_("fire:", None, 0.11)

    def fire_(self, _):  # noqa: N802
        if self._on_select:
            self._on_select(self._match_id)


class DropdownPanel:
    def __init__(self) -> None:
        self.on_select: Callable[[str], None] | None = None
        self._matches = []
        self._anchor = None
        self._window = self._build_window()
        self._visible = False

    def _build_window(self) -> NSWindow:
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, _WIDTH, 100),
            NSWindowStyleMaskBorderless, Cocoa.NSBackingStoreBuffered, False)
        win.setLevel_(NSScreenSaverWindowLevel)
        win.setCollectionBehavior_((1 << 1) | (1 << 8))  # MoveToActiveSpace|FSAux
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        return win

    def toggle(self, matches, anchor_window) -> None:
        if self._visible:
            self.hide()
        else:
            self.show(matches, anchor_window)

    def hide(self) -> None:
        self._window.orderOut_(None)
        self._visible = False

    def show(self, matches, anchor_window) -> None:
        self._matches = matches
        self._anchor = anchor_window
        total_h = self._layout(matches)
        self._window.setContentSize_(Cocoa.NSMakeSize(_WIDTH, total_h))
        self.reposition(anchor_window)
        self._window.orderFrontRegardless()
        self._visible = True

    def refresh_content(self, matches) -> None:
        """Rebuild the panel in place (e.g. after an auto-refresh tick)."""
        if not self._visible or self._anchor is None:
            return
        self.show(matches, self._anchor)

    def reposition(self, anchor_window) -> None:
        """Open the panel to the LEFT of the widget, top-aligned with it.
        Clamped to the screen; falls back to the right if there's no room left."""
        af = anchor_window.frame()
        h = self._window.frame().size.height
        gap = 6.0
        x = af.origin.x - _WIDTH - gap        # just left of the widget
        widget_top = af.origin.y + af.size.height
        y = widget_top - h                    # top of the panel = top of the widget

        screen = anchor_window.screen() or Cocoa.NSScreen.mainScreen()
        if screen is not None:
            vf = screen.visibleFrame()
            # If it would run off the left edge, place it to the right instead.
            if x < vf.origin.x + 4:
                x = af.origin.x + af.size.width + gap
            x = min(x, vf.origin.x + vf.size.width - _WIDTH - 4)
            y = max(vf.origin.y + 4, y)       # don't run off the bottom edge
        self._window.setFrameOrigin_(NSPoint(x, y))

    def _layout(self, matches) -> float:
        """Build the scrollable panel; return the visible window height."""
        # Order groups: live, finished, upcoming; India first within each.
        groups = [("in", "LIVE"), ("post", "FINISHED"), ("pre", "UPCOMING")]
        sections = []
        for state, label in groups:
            group = [m for m in matches if m.state == state]
            if group:
                group.sort(key=lambda m: (m.priority, m.short_name))
                sections.append((label, group))

        # Full content height (may exceed the visible cap).
        content_h = _PAD * 2
        for label, group in sections:
            content_h += _HDR_H + _ROW_H * len(group)
        visible_h = min(content_h, _MAX_H)

        win_rect = NSMakeRect(0, 0, _WIDTH, visible_h)
        effect = NSVisualEffectView.alloc().initWithFrame_(win_rect)
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(13.0)
        effect.layer().setMasksToBounds_(True)

        scrim = NSView.alloc().initWithFrame_(win_rect)
        scrim.setWantsLayer_(True)
        scrim.layer().setBackgroundColor_(_rgb(_SCRIM, 0.94).CGColor())
        scrim.layer().setCornerRadius_(13.0)
        scrim.layer().setBorderWidth_(0.5)
        scrim.layer().setBorderColor_(_white(0.14).CGColor())
        effect.addSubview_(scrim)

        # Scroll view fills the panel (inset for the rounded corners/border).
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(1, 1, _WIDTH - 2, visible_h - 2))
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(content_h > _MAX_H)
        scroll.setScrollerStyle_(1)  # NSScrollerStyleOverlay
        scroll.setAutohidesScrollers_(True)

        # Flipped document view holds all rows, laid out top-down.
        doc = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, _WIDTH - 2, content_h))
        y = _PAD
        for label, group in sections:
            hdr = self._label(NSMakeRect(12, y, _WIDTH - 24, _HDR_H),
                              9.5, 0.5, _rgb(_LIVE) if label == "LIVE" else _white(0.4))
            hdr.setStringValue_(f"{label}")
            doc.addSubview_(hdr)
            y += _HDR_H
            for m in group:
                row = RowView.alloc().initWithFrame_matchId_onSelect_(
                    NSMakeRect(6, y, _WIDTH - 14, _ROW_H), m.match_id, self._row_selected)
                flag = "🇮🇳" if m.has_india else "  "
                # Just the match name (with the tag appended so same-named
                # matches — a double-header — stay distinguishable). No detail.
                label = f"{flag} {m.short_name}"
                if m.match_tag:
                    label += f"   ({m.match_tag})"
                # Center the single line vertically in the row: a font-height box
                # placed at (row_h - box_h)/2 so text isn't top-anchored (which
                # left it floating high over the hover/selection highlight).
                _box_h = 16.0
                name = self._label(NSMakeRect(12, (_ROW_H - _box_h) / 2.0,
                                              _WIDTH - 26, _box_h), 12, 0.5,
                                   _white(0.95))
                name.setLineBreakMode_(Cocoa.NSLineBreakByTruncatingTail)
                name.setStringValue_(label)
                row.addSubview_(name)
                doc.addSubview_(row)
                y += _ROW_H

        scroll.setDocumentView_(doc)
        scrim.addSubview_(scroll)
        # Start scrolled at the top (document is flipped, so top = y 0).
        doc.scrollPoint_(NSPoint(0, 0))

        # Wrap the corner-radius'd effect view in a plain content view. Setting a
        # rounded NSVisualEffectView directly as the borderless window's content
        # view intermittently crashes the window corner-mask machinery.
        container = NSView.alloc().initWithFrame_(win_rect)
        container.addSubview_(effect)
        self._window.setContentView_(container)
        return visible_h

    def _row_selected(self, match_id: str) -> None:
        self.hide()
        if self.on_select:
            self.on_select(match_id)

    @staticmethod
    def _label(rect, size, weight, color, align="left") -> NSTextField:
        f = NSTextField.alloc().initWithFrame_(rect)
        f.setBezeled_(False)
        f.setDrawsBackground_(False)
        f.setEditable_(False)
        f.setSelectable_(False)
        f.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
        f.setTextColor_(color)
        if align == "right":
            f.setAlignment_(Cocoa.NSTextAlignmentRight)
        f.setStringValue_("")
        return f
