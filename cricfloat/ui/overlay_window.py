"""The always-on-top floating overlay window (PyObjC / AppKit).

A borderless, translucent scorecard panel that:
  * floats above all normal windows and over fullscreen apps, on every Space,
  * stays readable on light *or* dark backgrounds (solid dark scrim over blur),
  * is draggable by its body,
  * is clickable (opens the match page), has a match-picker dropdown and a
    close button,
  * never steals focus.

Interaction is wired through three callbacks set by the controller:
    on_click(url)        -> body clicked
    on_select(match_id)  -> dropdown selection changed
    on_close()           -> close button pressed
"""

from __future__ import annotations

import warnings
from typing import Callable

import Cocoa
import objc
from Cocoa import (
    NSButton,
    NSColor,
    NSFont,
    NSImage,
    NSImageView,
    NSIntersectionRect,
    NSIntersectsRect,
    NSMakeRect,
    NSPoint,
    NSScreen,
    NSTextField,
    NSView,
    NSVisualEffectView,
    NSWindow,
)

from .dropdown_panel import DropdownPanel
from .loader import Loader
from .render import CardView

warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)

NSScreenSaverWindowLevel = 1000
NSWindowStyleMaskBorderless = 0
NSVisualEffectMaterialHUDWindow = 13
NSVisualEffectStateActive = 1
NSVisualEffectBlendingModeBehindWindow = 0
NSWindowAnimationBehaviorNone = 2

_BEHAVIOR_MOVE_TO_ACTIVE_SPACE = 1 << 1
_BEHAVIOR_FULLSCREEN_AUXILIARY = 1 << 8

_W = 280.0
_H = 215.0  # room for header, chip, two rows, summary + 3 detail lines
_MARGIN = 22.0
_BAR = 4.0
_PADX = 15.0

# NSUserDefaults keys for the remembered window position.
_POS_KEY_X = "CricFloatWindowOriginX"
_POS_KEY_Y = "CricFloatWindowOriginY"

_LIVE = (0.30, 0.75, 0.47)
_CORAL = (1.0, 0.55, 0.50)
_SCRIM = (0.11, 0.12, 0.14)  # dark base painted over the blur for contrast

# Per-ball circle colors, keyed by ball kind.
_BALL_COLORS = {
    "dot": (0.32, 0.34, 0.38),     # muted gray
    "run": (0.20, 0.42, 0.62),     # blue
    "four": (0.16, 0.55, 0.35),    # green
    "six": (0.45, 0.30, 0.62),     # purple
    "wicket": (0.72, 0.22, 0.22),  # red
    "wide": (0.72, 0.52, 0.16),    # amber — extras
    "noball": (0.72, 0.52, 0.16),  # amber — extras
    "bye": (0.30, 0.50, 0.55),     # teal
}

_BALL_D = 20.0        # ball tile size (rounded square)
_BALL_RADIUS = 5.0    # corner radius — rounded square, not a full circle
_BALL_GAP = 4.0       # gap between balls
_OVER_GAP = 9.0       # extra gap at an over boundary


def _ball_color(kind: str):
    return _BALL_COLORS.get(kind, _BALL_COLORS["run"])


def _white(a: float):
    return NSColor.colorWithCalibratedWhite_alpha_(1.0, a)


def _rgb(rgb, a: float = 1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], a)


def _text_width(text: str, font) -> float:
    """Rendered width of `text` in `font` (points)."""
    s = Cocoa.NSString.stringWithString_(text)
    return s.sizeWithAttributes_({Cocoa.NSFontAttributeName: font}).width


class ClickableView(NSView):
    """The panel body. Dragging anywhere moves the window. A plain click (no
    drag) reports to the overlay so it can close the dropdown. The ESPN link is
    opened only from the ↗ button, not the body."""

    def initWithFrame_(self, frame):  # noqa: N802
        self = objc.super(ClickableView, self).initWithFrame_(frame)
        if self is not None:
            self._on_click = None
            self._on_drag = None
            self._on_drag_end = None
            self._dragged = False
        return self

    def setOnClick_(self, cb):  # noqa: N802
        self._on_click = cb

    def setOnDrag_(self, cb):  # noqa: N802
        self._on_drag = cb

    def setOnDragEnd_(self, cb):  # noqa: N802
        self._on_drag_end = cb

    def mouseDown_(self, event):  # noqa: N802
        self._dragged = False

    def mouseDragged_(self, event):  # noqa: N802
        self._dragged = True
        win = self.window()
        f = win.frame()
        win.setFrameOrigin_(NSPoint(f.origin.x + event.deltaX(),
                                    f.origin.y - event.deltaY()))
        if self._on_drag is not None:
            self._on_drag()

    def mouseUp_(self, event):  # noqa: N802
        if self._dragged:
            # Drag finished — persist the new position (once, not per delta).
            if self._on_drag_end is not None:
                self._on_drag_end()
        elif self._on_click is not None:
            # A plain click (no drag) notifies the overlay (used to close dropdown).
            self._on_click()


class _FlippedView(NSView):
    """A view with a top-left origin, so children lay out top-down."""

    def isFlipped(self):  # noqa: N802
        return True


class DraggableWindow(NSWindow):
    def canBecomeKeyWindow(self):  # noqa: N802
        return False

    def canBecomeMainWindow(self):  # noqa: N802
        return False


class HoverButton(NSButton):
    """A borderless icon/arrow button that brightens on hover, so anything
    clickable gives the same feedback as the dropdown rows. Enter/exit swap
    the content tint between a base and a full-white hover color; a light
    rounded background also fades in so the hit area is obvious.

    On hover it also asks the overlay (via `_hint_cb`) to show a themed tooltip
    above the widget describing what the button does."""

    def initWithFrame_baseAlpha_(self, frame, base_alpha):  # noqa: N802
        self = objc.super(HoverButton, self).initWithFrame_(frame)
        if self is not None:
            self._base_alpha = base_alpha
            self._hint = ""          # tooltip text; set by the overlay
            self._hint_cb = None     # callback(text_or_None) to show/hide tooltip
            self.setWantsLayer_(True)
            self.layer().setCornerRadius_(5.0)
            self._add_tracking()
        return self

    def setHint_callback_(self, text, cb):  # noqa: N802
        self._hint = text
        self._hint_cb = cb

    def _add_tracking(self):
        # MouseEnteredAndExited (0x01) | ActiveAlways (0x80) | InVisibleRect (0x200)
        opts = 0x01 | 0x80 | 0x200
        area = Cocoa.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), opts, self, None)
        self.addTrackingArea_(area)

    def mouseEntered_(self, event):  # noqa: N802
        self.setContentTintColor_(_white(1.0))
        self.layer().setBackgroundColor_(_white(0.12).CGColor())
        if self._hint_cb is not None and self._hint:
            self._hint_cb(self._hint)

    def mouseExited_(self, event):  # noqa: N802
        self.setContentTintColor_(_white(self._base_alpha))
        self.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
        if self._hint_cb is not None:
            self._hint_cb(None)


class HintTooltip:
    """A tiny dark tooltip that floats just ABOVE the widget, describing the
    hovered button. Its own borderless window (so it can sit outside the widget's
    bounds); sized to its text and centered over the widget."""

    _H = 24.0  # tooltip height
    _GAP = 6.0  # gap between the tooltip's bottom and the widget's top

    def __init__(self) -> None:
        self._label = None      # set inside _build()
        self._visible = False
        self._window = self._build()

    def _build(self) -> NSWindow:
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 120, self._H),
            NSWindowStyleMaskBorderless, Cocoa.NSBackingStoreBuffered, False)
        win.setLevel_(NSScreenSaverWindowLevel)
        win.setCollectionBehavior_(
            _BEHAVIOR_MOVE_TO_ACTIVE_SPACE | _BEHAVIOR_FULLSCREEN_AUXILIARY)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setIgnoresMouseEvents_(True)  # never steal hover/clicks from the widget

        # Plain rounded dark pill (no NSVisualEffectView as contentView — that
        # corner-mask combo has crashed before).
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 120, self._H))
        container.setWantsLayer_(True)
        container.layer().setBackgroundColor_(_rgb(_SCRIM, 0.96).CGColor())
        container.layer().setCornerRadius_(6.0)
        container.layer().setBorderWidth_(0.5)
        container.layer().setBorderColor_(_white(0.16).CGColor())

        lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 3, 100, 17))
        lbl.setBezeled_(False)
        lbl.setDrawsBackground_(False)
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        lbl.setFont_(NSFont.systemFontOfSize_weight_(11.5, 0.4))
        lbl.setTextColor_(_white(0.92))
        lbl.setAlignment_(Cocoa.NSTextAlignmentCenter)
        container.addSubview_(lbl)
        self._label = lbl
        win.setContentView_(container)
        return win

    def show(self, text: str, anchor_window: NSWindow) -> None:
        """Show `text` centered just above `anchor_window` (the widget)."""
        f = self._label.font()
        w = _text_width(text, f) + 22.0  # padding either side
        self._label.setStringValue_(text)
        self._label.setFrame_(NSMakeRect(0, 3, w, 17))
        cv = self._window.contentView()
        cv.setFrame_(NSMakeRect(0, 0, w, self._H))
        self._window.setContentSize_(Cocoa.NSMakeSize(w, self._H))

        af = anchor_window.frame()
        x = af.origin.x + (af.size.width - w) / 2.0     # centered over widget
        y = af.origin.y + af.size.height + self._GAP    # just above widget top
        # Clamp to the screen so it never runs off the top edge.
        screen = anchor_window.screen() or Cocoa.NSScreen.mainScreen()
        if screen is not None:
            vf = screen.visibleFrame()
            top = vf.origin.y + vf.size.height - self._H - 2
            if y > top:  # no room above -> tuck it just below the widget top
                y = af.origin.y + af.size.height - self._H - self._GAP
            x = max(vf.origin.x + 2,
                    min(x, vf.origin.x + vf.size.width - w - 2))
        self._window.setFrameOrigin_(NSPoint(x, y))
        self._window.orderFrontRegardless()
        self._visible = True

    def hide(self) -> None:
        if self._visible:
            self._window.orderOut_(None)
            self._visible = False


class SpaceObserver(Cocoa.NSObject):
    """Receives NSWorkspace active-space-change notifications and asks the
    overlay to re-show itself (and its dropdown) on the newly active Space."""

    def initWithOverlay_(self, overlay):  # noqa: N802
        self = objc.super(SpaceObserver, self).init()
        if self is not None:
            self._overlay = overlay
        return self

    def spaceChanged_(self, note):  # noqa: N802
        self._overlay._on_space_changed()


class ScreenObserver(Cocoa.NSObject):
    """Receives screen-parameter-change notifications (display added/removed,
    resolution or arrangement change) and asks the overlay to rescue itself back
    on-screen if the change left it stranded off every display."""

    def initWithOverlay_(self, overlay):  # noqa: N802
        self = objc.super(ScreenObserver, self).init()
        if self is not None:
            self._overlay = overlay
        return self

    def screensChanged_(self, note):  # noqa: N802
        self._overlay._on_screens_changed()


class OverlayWindow:
    def __init__(self) -> None:
        self.on_click: Callable[[str], None] | None = None
        self.on_select: Callable[[str], None] | None = None
        self.on_close: Callable[[], None] | None = None
        self.on_refresh: Callable[[], None] | None = None

        self._url = ""
        self._matches: list = []
        self._expanded = False  # batsmen/bowler detail collapsed by default
        self._card = None       # last rendered card (for re-render on toggle)
        self._dropdown = DropdownPanel()
        self._dropdown.on_select = self._panel_selected
        self._hint = HintTooltip()  # floats above the widget on button hover

        self._hidden = False  # True when the user hid the widget (via ✕ / menu)
        self._window = self._build_window()
        self._build_views()
        self._window.orderFrontRegardless()
        self._subscribe_space_changes()

    def _show_hint(self, text) -> None:
        """HoverButton callback: show `text` above the widget, or hide (text=None).
        Suppressed while the match dropdown is open (it would overlap)."""
        if text and not self._dropdown._visible:
            self._hint.show(text, self._window)
        else:
            self._hint.hide()

    def _on_space_changed(self) -> None:
        # Don't resurrect a widget the user hid — a Space swipe shouldn't bring it
        # back (that's what the menu-bar Show is for).
        if self._hidden:
            return
        # Pull the widget onto the now-active Space; close the dropdown if open
        # (simpler than trying to move a scrolling panel across Spaces).
        self._window.orderFrontRegardless()
        self._hint.hide()
        if self._dropdown._visible:
            self._dropdown.hide()
            self._sync_trigger_arrow()

    def _subscribe_space_changes(self) -> None:
        self._space_observer = SpaceObserver.alloc().initWithOverlay_(self)
        nc = Cocoa.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserver_selector_name_object_(
            self._space_observer,
            "spaceChanged:",
            "NSWorkspaceActiveSpaceDidChangeNotification",
            None,
        )
        # Screen-parameter changes (display added/removed, resolution/arrangement
        # change) come from the app's default center, not NSWorkspace's.
        self._screen_observer = ScreenObserver.alloc().initWithOverlay_(self)
        Cocoa.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self._screen_observer,
            "screensChanged:",
            "NSApplicationDidChangeScreenParametersNotification",
            None,
        )

    def _on_screens_changed(self) -> None:
        # The display setup changed. If the widget is now off every screen (e.g.
        # its monitor was unplugged, or a resolution drop pushed it past the
        # edge), move it back somewhere visible. If it's still on a screen, leave
        # it where the user put it.
        self._rescue_if_offscreen()
        if self._dropdown._visible:  # keep the panel pinned to the moved widget
            self._dropdown.reposition(self._window)

    def _rescue_if_offscreen(self) -> None:
        """Reposition the widget only when its frame no longer meaningfully
        overlaps any active screen — so a deliberate custom position is left
        alone, but a stranded widget is brought back."""
        wf = self._window.frame()
        for screen in NSScreen.screens() or []:
            if NSIntersectsRect(wf, screen.visibleFrame()):
                inter = NSIntersectionRect(wf, screen.visibleFrame())
                # Consider it "on-screen" only if a usable chunk is visible, so a
                # 1px sliver still counts as stranded.
                if inter.size.width >= 40 and inter.size.height >= 20:
                    return
        # Stranded — snap back to the default top-right of the main screen, and
        # persist that safe position so the stale off-screen one isn't retried.
        self._position_top_right(self._window)
        self._save_position()

    # ---- public API ----------------------------------------------------

    def set_card(self, card: CardView) -> None:
        self._card = card
        self._url = card.url
        self._header.setStringValue_(card.header)
        self._chip.setStringValue_(("● " + card.chip) if card.live else card.chip)
        self._chip.setTextColor_(_rgb(_LIVE) if card.live else _white(0.55))
        self._bar.setHidden_(not card.live)

        rows = card.rows[:2]
        # Size the overs column to the WIDEST overs value shown, so short overs
        # (e.g. "9.5") don't leave a big gap before the score. The score column's
        # right edge = panel edge − overs column − a small gap.
        any_overs = any(r.overs for r in rows)
        overs_col_w = 0.0
        if any_overs:
            font = self._rows[0][3].font()
            for r in rows:
                if r.overs:
                    w = _text_width(r.overs, font)
                    overs_col_w = max(overs_col_w, w)
            overs_col_w += 6.0  # pad so the last digit isn't clipped
        gap = 8.0
        score_right = (self._right - overs_col_w - gap) if any_overs else self._right
        overs_x = score_right + gap

        for i in range(2):
            name_f, bat_f, score_f, overs_f = self._rows[i]
            if i < len(rows):
                r = rows[i]
                name_f.setStringValue_(r.name)
                no_score = not r.score or r.score == "yet to bat"
                # "—" as a compact, quiet placeholder instead of big "yet to bat".
                score_f.setStringValue_("" if no_score else r.score)
                overs_f.setStringValue_(r.overs)
                # Position overs (right-aligned to the panel edge) and the score
                # (right-aligned just left of the overs column). A row with no
                # overs extends the score to the full right edge.
                of = overs_f.frame()
                overs_f.setFrame_(NSMakeRect(overs_x, of.origin.y,
                                             self._right - overs_x, of.size.height))
                sf = score_f.frame()
                right = score_right if r.overs else self._right
                score_f.setFrame_(NSMakeRect(self._name_x, sf.origin.y,
                                             right - self._name_x, sf.size.height))
                # A small dimmed dash marks a team that hasn't batted yet.
                self._yet_marks[i].setHidden_(not no_score)
                bat_f.setHidden_(not r.batting)
                if r.batting:
                    name_w = name_f.attributedStringValue().size().width
                    nf = name_f.frame()
                    bf = bat_f.frame()
                    bat_f.setFrameOrigin_(NSPoint(nf.origin.x + name_w + 6,
                                                  bf.origin.y))
                # Brightness (not color) distinguishes the highlighted team. The
                # non-highlighted (e.g. already-batted) innings is dimmed harder so
                # the eye lands on the live innings first.
                strong = r.emphasis
                name_f.setTextColor_(_white(1.0 if strong else 0.45))
                score_f.setTextColor_(_white(1.0 if strong else 0.5))
                overs_f.setTextColor_(_white(0.4 if strong else 0.28))
            else:
                name_f.setStringValue_("")
                bat_f.setHidden_(True)
                score_f.setStringValue_("")
                overs_f.setStringValue_("")
                self._yet_marks[i].setHidden_(True)

        self._summary.setStringValue_(card.summary)
        self._summary.setTextColor_(_rgb(_LIVE) if card.live else _rgb(_CORAL))
        # Interruption note on a 2nd line (rain/bad light/…). Present => everything
        # below shifts down by _NOTE_H (handled in _resize_for).
        self._has_note = bool(card.note)
        self._summary_note.setStringValue_(card.note or "")
        self._summary_note.setHidden_(not self._has_note)
        self._render_balls(card.balls)

        # Collapsible detail. The chevron shows for any LIVE match; when
        # expanded it reveals the batsmen/bowler (one per line), or a note when
        # ESPN has no player data (some minor leagues).
        self._chevron.setHidden_(not card.has_detail)
        self._chevron.setTitle_(
            "BATSMEN & BOWLER  ▴" if self._expanded else "BATSMEN & BOWLER  ▾")
        self._chevron.setHint_callback_(
            "Hide batsmen & bowler" if self._expanded else "Show batsmen & bowler",
            self._show_hint)
        expand = card.has_detail and self._expanded
        self._render_detail(card.detail if expand else [], show=expand)

        self._resize_for(card)

    def _render_detail(self, detail, show: bool) -> None:
        """Render the expanded detail grouped into a BATTING section (one row per
        batsman) and a BOWLING section (the bowler), each with a small header, so
        it's clear which is which. Empty detail shows a 'no data' note."""
        c = self._detail_container
        for sub in list(c.subviews()):
            sub.removeFromSuperview()
        c.setHidden_(not show)
        if not show:
            self._detail_h = 0.0
            return

        inner_w = c.frame().size.width
        row_h = 20.0
        hdr_h = 15.0
        y = 0.0  # top-down in the (flipped) container

        if not detail:
            note = self._label(NSMakeRect(0, 2, inner_w, 16), 11.5, 0.3, _white(0.4))
            note.setStringValue_("Player data unavailable")
            c.addSubview_(note)
            self._detail_h = row_h
            return

        bats = [d for d in detail if d.kind == "bat"]
        bowls = [d for d in detail if d.kind == "bowl"]

        def section_header(label, yy):
            h = self._label(NSMakeRect(0, yy, inner_w, hdr_h), 9.0, 0.6, _white(0.4))
            h.setStringValue_(label.upper())
            c.addSubview_(h)

        def player_row(d, yy):
            # On-strike is conveyed by the '*' on the score (e.g. "42*"), so the
            # name needs no extra marker.
            name = self._label(NSMakeRect(0, yy, inner_w * 0.62, 16), 12.5, 0.5,
                               _white(0.92))
            name.setStringValue_(d.name)
            fig = self._label(NSMakeRect(inner_w * 0.4, yy, inner_w * 0.6, 16),
                             12.5, 0.5, _white(0.95), align="right", mono=True)
            fig.setStringValue_(d.figure)
            c.addSubview_(name)
            c.addSubview_(fig)

        if bats:
            section_header("Batting", y); y += hdr_h
            for d in bats:
                player_row(d, y); y += row_h
        if bowls:
            y += 3  # small gap between sections
            section_header("Bowling", y); y += hdr_h
            for d in bowls:
                player_row(d, y); y += row_h
        self._detail_h = y

    def start_loading(self) -> None:
        """Blank the score area and show only the spinning ball, so no partial
        data is visible while the match's full data is fetched."""
        for v in self._content_views:
            v.setHidden_(True)
        self._bar.setHidden_(True)
        self._chevron.setHidden_(True)
        self._summary_note.setHidden_(True)
        self._detail_container.setHidden_(True)
        for _n, bat, _s, _o in self._rows:
            bat.setHidden_(True)
        for yet in self._yet_marks:
            yet.setHidden_(True)
        # Use a compact fixed height while loading and center the spinner in it.
        self._set_height(self._LOADING_H)
        self._recenter_loader(self._LOADING_H)
        self._loader.show()

    def stop_loading(self) -> None:
        """Reveal the content again (called once all data is ready). The accent
        bar and bat markers are left to set_card, which runs right after."""
        self._loader.hide()
        for v in self._content_views:
            v.setHidden_(False)

    # Distance from the TOP of the widget to the BOTTOM of each content line
    # (measured from the build layout). Used to size the widget to just its
    # visible content, avoiding empty space at the bottom.
    _HEADER_BOTTOM = 54.0     # bottom of picker + venue/icons band
    _SUMMARY_BOTTOM = 125.0
    _BALLS_BOTTOM = 151.0     # recent-balls strip (moved above the detail)
    _CHEVRON_BOTTOM = 176.0   # labeled section toggle ("BATSMEN & BOWLER ▾")
    _DETAIL_TOP = 182.0       # detail container starts here (distance from top)
    _BOTTOM_PAD = 12.0        # padding below the last content line
    _LOADING_H = 120.0        # compact height shown while loading
    _NOTE_H = 18.0            # height added by the interruption note (2nd summary line)

    # Vertical space the recent-balls strip occupies. When a live match has no
    # balls data (e.g. ENG19 v SA19), the chevron + detail slide up by this much
    # so there's no empty gap where the strip would be.
    _BALLS_STRIP_H = _BALLS_BOTTOM - _SUMMARY_BOTTOM

    def _resize_for(self, card) -> None:
        """Grow/shrink the widget to fit only the visible content. The expanded
        detail (variable number of player rows) counts toward the height only
        when expanded."""
        has_balls = bool(card.balls)
        # An interruption note adds a 2nd summary line, pushing everything below
        # it DOWN by _NOTE_H. No balls -> collapse the strip's slot and pull the
        # chevron/detail UP. The two shifts combine.
        note_shift = self._NOTE_H if getattr(self, "_has_note", False) else 0.0
        shift = (0.0 if has_balls else self._BALLS_STRIP_H) - note_shift
        balls_bottom = self._BALLS_BOTTOM + note_shift
        chevron_bottom = self._CHEVRON_BOTTOM - shift
        detail_top = self._DETAIL_TOP - shift

        # Re-pin the balls strip and chevron. _top_offsets stores each view's TOP
        # edge distance from the widget top (subtract the box height from the
        # bottom offset).
        balls_h = self._balls_container.frame().size.height
        self._top_offsets[self._balls_container] = balls_bottom - balls_h
        chev_h = self._chevron.frame().size.height
        self._top_offsets[self._chevron] = chevron_bottom - chev_h

        # Collapsed content: summary (+note), then balls (if any), then chevron.
        content_bottom = self._SUMMARY_BOTTOM + note_shift
        if has_balls:
            content_bottom = balls_bottom
        if card.live:  # chevron shows for any live match
            content_bottom = chevron_bottom

        # Expanded: add the detail rows below the chevron (dynamic height).
        if card.live and self._expanded:
            content_bottom = detail_top + self._detail_h

        new_h = content_bottom + self._BOTTOM_PAD
        # Pin the detail container just below the chevron in the resized widget.
        dc = self._detail_container
        dc.setFrame_(NSMakeRect(dc.frame().origin.x,
                                new_h - detail_top - self._detail_h,
                                dc.frame().size.width, max(self._detail_h, 1.0)))
        self._set_height(new_h)

    def _set_height(self, new_h: float) -> None:
        """Resize the widget to `new_h`, keeping the TOP edge fixed. Content is
        re-pinned to the top from its saved top-offset (idempotent — safe to call
        every render). The picker/close/icons all live at the top now."""
        cur = self._window.frame()
        if abs(cur.size.height - new_h) < 0.5:
            return
        delta = new_h - cur.size.height
        # Keep top-left fixed: window grows/shrinks at the bottom.
        self._window.setFrame_display_(
            NSMakeRect(cur.origin.x, cur.origin.y - delta, _W, new_h), True)

        effect = self._window.contentView()
        effect.setFrame_(NSMakeRect(0, 0, _W, new_h))
        body = effect.subviews()[0]
        body.setFrame_(NSMakeRect(0, 0, _W, new_h))

        # Re-pin each content view to its stored distance-from-top. `top` is the
        # gap above the view's top edge, so origin.y = new_h - top - height.
        for view, top in self._top_offsets.items():
            f = view.frame()
            view.setFrameOrigin_(NSPoint(f.origin.x, new_h - top - f.size.height))

        # Accent bar spans the full new height.
        bf = self._bar.frame()
        self._bar.setFrame_(NSMakeRect(bf.origin.x, 0, bf.size.width, new_h))
        self._recenter_loader(new_h)

        # If the dropdown is open, the taller/shorter widget would overlap it.
        # Re-pin the panel below the new widget bounds and keep it in front so
        # neither hides the other.
        if self._dropdown._visible:
            self._dropdown.reposition(self._window)
            self._dropdown._window.orderFront_(None)

    def _recenter_loader(self, height: float) -> None:
        # Center the spinner in the score area (below the top picker/venue rows).
        self._loader.set_center(_W / 2.0, (height - self._HEADER_BOTTOM) / 2.0)

    def _render_balls(self, balls) -> None:
        """Draw each recent ball as a small colored pill with its symbol. Single
        chars ('4', 'W') are circles; multi-char extras ('wd', 'nb') are pills.
        An over boundary draws a thin vertical divider centered in the gap."""
        container = self._balls_container
        for sub in list(container.subviews()):
            sub.removeFromSuperview()

        # Widths of each pill (multi-char extras like 'wd' are wider).
        widths = [
            _BALL_D + (max(0, len(b.symbol) - 1) * 5.0 if len(b.symbol) > 1 else 0.0)
            for b in balls
        ]
        n_overs = sum(1 for i, b in enumerate(balls) if b.over_start and i > 0)
        # Shrink the inter-ball / over gaps together if the row would otherwise
        # reach the edge, so a 2-over-boundary row stays evenly spaced with a
        # little right margin instead of crowding the last ball against the edge.
        avail = container.frame().size.width - 4.0  # small right breathing room
        pills_w = sum(widths)
        gaps = max(len(balls) - 1, 0)
        want = pills_w + gaps * _BALL_GAP + n_overs * (_OVER_GAP - _BALL_GAP)
        scale = min(1.0, (avail - pills_w) / (want - pills_w)) if want > pills_w else 1.0
        ball_gap = _BALL_GAP * scale
        over_gap = _OVER_GAP * scale

        x = 0.0
        for i, b in enumerate(balls):
            if b.over_start and i > 0:
                # The gap between the previous pill and this one is over_gap
                # wide; put the divider in its exact middle.
                gap_start = x - ball_gap            # right edge of previous pill
                x = gap_start + over_gap            # this pill starts here
                sep_x = gap_start + over_gap / 2.0  # divider centered in the gap
                sep = NSView.alloc().initWithFrame_(
                    NSMakeRect(sep_x - 0.5, 3, 1.0, _BALL_D - 4))
                sep.setWantsLayer_(True)
                sep.layer().setBackgroundColor_(_white(0.30).CGColor())
                container.addSubview_(sep)

            # A dot ball uses a centered middle-dot glyph; digits/letters as-is.
            symbol = "•" if b.symbol == "." else b.symbol
            font = 12.5 if len(b.symbol) <= 1 else 10.5
            w = widths[i]

            pill = NSView.alloc().initWithFrame_(NSMakeRect(x, 1, w, _BALL_D))
            pill.setWantsLayer_(True)
            pill.layer().setBackgroundColor_(_rgb(_ball_color(b.kind)).CGColor())
            # A rounded square (fixed small radius) rather than a full circle.
            pill.layer().setCornerRadius_(_BALL_RADIUS)
            # Vertically center the glyph (NSTextField sits text on its baseline).
            lbl_h = font + 4.0
            lbl = self._label(NSMakeRect(0, (_BALL_D - lbl_h) / 2.0, w, lbl_h),
                              font, 0.6, _white(0.98), align="center")
            lbl.setStringValue_(symbol)
            pill.addSubview_(lbl)
            container.addSubview_(pill)
            x += w + ball_gap

    def set_matches(self, matches, selected_id) -> None:
        """Store the match list for the custom dropdown panel and update the
        trigger button's label to the current selection."""
        self._matches = list(matches)
        selected = next((m for m in matches if m.match_id == selected_id), None)
        self._trigger_label = selected.short_name if selected else "Match"
        self._sync_trigger_arrow()
        # Keep the open panel in sync if it's showing.
        if self._dropdown._visible:
            self._dropdown.refresh_content(self._matches)

    def _sync_trigger_arrow(self) -> None:
        """Point the trigger arrow the opposite way when the panel is open:
        ◂ (closed) → ▸ (open). Also re-hug the text width after retitling."""
        arrow = "▸" if self._dropdown._visible else "◂"
        self._trigger.setTitle_(f"{arrow}  {self._trigger_label}")
        # Shrink the button to hug its text, so only the text/arrow toggles the
        # dropdown and the rest of the row is draggable body.
        self._trigger.sizeToFit()
        tf = self._trigger.frame()
        self._trigger.setFrame_(NSMakeRect(self._trigger_x, tf.origin.y,
                                           tf.size.width, 20))

    def show(self) -> None:
        self._hidden = False
        self._window.orderFrontRegardless()

    def hide(self) -> None:
        self._hidden = True
        self._hint.hide()
        # Close the match dropdown (and reset its arrow) if it was open.
        if self._dropdown._visible:
            self._dropdown.hide()
            self._sync_trigger_arrow()
        # Collapse the batsmen/bowler detail so the widget reopens compact.
        if self._expanded:
            self._expanded = False
            if self._card is not None:
                self.set_card(self._card)
        self._window.orderOut_(None)

    # ---- Cocoa action targets (called by buttons/popups) ---------------

    def _body_clicked(self) -> None:
        # A click anywhere on the widget (that isn't a button) just closes the
        # dropdown if it's open. The ESPN link opens only from the ↗ button.
        if self._dropdown._visible:
            self._dropdown.hide()
            self._sync_trigger_arrow()

    def _body_dragged(self) -> None:
        # Keep the dropdown pinned to the widget while it's dragged.
        if self._dropdown._visible:
            self._dropdown.reposition(self._window)

    def triggerClicked_(self, sender):  # noqa: N802
        self._hint.hide()  # the dropdown would overlap the tooltip
        self._dropdown.toggle(self._matches, self._window)
        self._sync_trigger_arrow()

    def _panel_selected(self, match_id: str) -> None:
        # A new match starts collapsed (the detail may differ / not exist).
        self._expanded = False
        if self.on_select:
            self.on_select(match_id)

    @staticmethod
    def _flash(view) -> None:
        """Quick press feedback: dip the view's opacity and spring it back, so a
        tap on an icon/button reads as a click even though it's a borderless HUD.
        Uses the layer's implicit animation, so it's cheap and self-restoring."""
        view.setWantsLayer_(True)
        layer = view.layer()
        if layer is None:
            return
        anim = Cocoa.CABasicAnimation.animationWithKeyPath_("opacity")
        anim.setFromValue_(0.25)
        anim.setToValue_(1.0)
        anim.setDuration_(0.22)
        layer.addAnimation_forKey_(anim, "press")

    def closeClicked_(self, sender):  # noqa: N802
        self._flash(sender)
        if self.on_close:
            self.on_close()

    def refreshClicked_(self, sender):  # noqa: N802
        self._flash(sender)
        if self.on_refresh:
            self.on_refresh()

    def chevronClicked_(self, sender):  # noqa: N802
        # Toggle the batsmen/bowler detail; re-render the last card in the new
        # state so the widget grows/shrinks and the arrow flips.
        self._hint.hide()  # re-shows with the flipped label on next hover
        self._expanded = not self._expanded
        if self._card is not None:
            self.set_card(self._card)

    def openClicked_(self, sender):  # noqa: N802
        self._flash(sender)
        if self.on_click and self._url:
            self.on_click(self._url)

    # ---- construction --------------------------------------------------

    def _build_window(self) -> NSWindow:
        rect = NSMakeRect(0, 0, _W, _H)
        win = DraggableWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, Cocoa.NSBackingStoreBuffered, False
        )
        win.setLevel_(NSScreenSaverWindowLevel)
        # Do NOT join all Spaces — that mode re-composites the window on every
        # swipe, which is the flicker. Instead the window lives on one Space and
        # we move it onto the active Space when the user switches (see
        # _subscribe_space_changes). MoveToActiveSpace makes orderFront pull it
        # to whatever Space is current. FullScreenAuxiliary keeps it over
        # fullscreen apps.
        win.setCollectionBehavior_(
            _BEHAVIOR_MOVE_TO_ACTIVE_SPACE
            | _BEHAVIOR_FULLSCREEN_AUXILIARY
        )
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        # Don't animate with Space transitions — reduces the swipe flicker.
        win.setAnimationBehavior_(NSWindowAnimationBehaviorNone)

        # Blur backdrop...
        effect = NSVisualEffectView.alloc().initWithFrame_(rect)
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(13.0)
        effect.layer().setMasksToBounds_(True)
        win.setContentView_(effect)

        # Restore the last dragged position if we have one AND it's still on a
        # screen; otherwise fall back to the default top-right.
        if not self._restore_position(win):
            self._position_top_right(win)
        return win

    def _position_top_right(self, win: NSWindow) -> None:
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        vf = screen.visibleFrame()
        # Leave a bit more room at the TOP than the side, so the hover tooltip
        # (which floats above the widget) has space to sit there by default.
        top_margin = _MARGIN + 20.0
        win.setFrameOrigin_(NSPoint(
            vf.origin.x + vf.size.width - _W - _MARGIN,
            vf.origin.y + vf.size.height - _H - top_margin,
        ))

    def _save_position(self) -> None:
        """Persist the window's current origin so it reopens where the user left
        it. Called once when a drag ends."""
        f = self._window.frame()
        d = Cocoa.NSUserDefaults.standardUserDefaults()
        d.setDouble_forKey_(f.origin.x, _POS_KEY_X)
        d.setDouble_forKey_(f.origin.y, _POS_KEY_Y)

    def _restore_position(self, win: NSWindow) -> bool:
        """Move `win` to the saved origin. Returns True only if a position was
        stored AND it lands on-screen (so a stale off-screen coordinate — e.g.
        from a since-unplugged monitor — falls back to the default instead of
        opening the widget somewhere invisible)."""
        d = Cocoa.NSUserDefaults.standardUserDefaults()
        if d.objectForKey_(_POS_KEY_X) is None or d.objectForKey_(_POS_KEY_Y) is None:
            return False
        origin = NSPoint(d.doubleForKey_(_POS_KEY_X), d.doubleForKey_(_POS_KEY_Y))
        frame = NSMakeRect(origin.x, origin.y, _W, _H)
        for screen in NSScreen.screens() or []:
            if NSIntersectsRect(frame, screen.visibleFrame()):
                inter = NSIntersectionRect(frame, screen.visibleFrame())
                if inter.size.width >= 40 and inter.size.height >= 20:
                    win.setFrameOrigin_(origin)
                    return True
        return False

    def _build_views(self) -> None:
        effect = self._window.contentView()
        rect = NSMakeRect(0, 0, _W, _H)

        # ...with a solid dark scrim on top, so text stays readable on any
        # background (light desktops washed out the blur alone). This clickable
        # scrim is also the drag/click surface.
        body = ClickableView.alloc().initWithFrame_(rect)
        body.setWantsLayer_(True)
        body.layer().setBackgroundColor_(_rgb(_SCRIM, 0.90).CGColor())
        body.layer().setCornerRadius_(13.0)
        body.layer().setBorderWidth_(0.5)
        body.layer().setBorderColor_(_white(0.14).CGColor())
        body.setOnClick_(self._body_clicked)
        body.setOnDrag_(self._body_dragged)
        body.setOnDragEnd_(self._save_position)
        effect.addSubview_(body)

        # Left accent bar (live only).
        bar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _BAR, _H))
        bar.setWantsLayer_(True)
        bar.layer().setBackgroundColor_(_rgb(_LIVE).CGColor())
        bar.setHidden_(True)
        body.addSubview_(bar)
        self._bar = bar

        left = _BAR + _PADX
        inner_w = _W - left - _PADX
        self._right = left + inner_w  # panel's inner right edge
        self._name_x = left           # left edge of the score/name column
        # Initial score-right; recomputed per render from the widest overs value.
        self._score_right = self._right - 40.0
        # Reserve the top-right corner for the close button; the chip sits on the
        # line below it, flush to the right edge.
        close_w = 16.0

        # --- Row 1 (top): ◂ match picker (left) · ● chip + ✕ close (right) ---
        chip_w = 72.0  # wide enough for "UPCOMING"
        # Dropdown picker as the top row. The button is sized to just its text
        # (via set_matches -> sizeToFit) so only the text/arrow opens the
        # dropdown; the empty area beside it belongs to the body (draggable).
        # The arrow points LEFT since the panel opens to the widget's left.
        trigger = HoverButton.alloc().initWithFrame_baseAlpha_(
            NSMakeRect(left - 2, _H - 27, inner_w - chip_w - close_w + 2, 20), 0.92)
        trigger.setBordered_(False)
        trigger.setFont_(NSFont.systemFontOfSize_weight_(13.0, 0.4))
        trigger.setTitle_("◂  Match")
        trigger.setContentTintColor_(_white(0.92))
        trigger.setAlignment_(Cocoa.NSTextAlignmentLeft)
        trigger.setTarget_(self)
        trigger.setAction_("triggerClicked:")
        trigger.setHint_callback_("Switch match", self._show_hint)
        body.addSubview_(trigger)
        self._trigger = trigger
        self._trigger_y = _H - 27
        self._trigger_x = left - 2
        self._trigger_label = "Match"  # current selection text (arrow prepended)

        # Close button flush to the right edge.
        close = HoverButton.alloc().initWithFrame_baseAlpha_(
            NSMakeRect(_W - _PADX - close_w, _H - 26, close_w, 16), 0.82)
        close.setBordered_(False)
        close.setTitle_("✕")
        close.setFont_(NSFont.systemFontOfSize_(12))
        close.setContentTintColor_(_white(0.82))
        close.setTarget_(self)
        close.setAction_("closeClicked:")
        close.setHint_callback_("Hide widget (Quit from menu bar)", self._show_hint)
        body.addSubview_(close)
        self._close = close

        # Chip just left of the close button.
        self._chip = self._label(
            NSMakeRect(_W - _PADX - close_w - chip_w - 2, _H - 25, chip_w, 14),
            10.0, 0.5, _white(0.55), align="right")
        body.addSubview_(self._chip)

        # --- Row 2: venue/format (left) · ↻ refresh, ↗ open (right) ---
        icon_w = 15.0  # snug around the glyph so the two icons sit close together
        self._header = self._label(
            NSMakeRect(left, _H - 46, inner_w - 2 * icon_w - 6, 14),
            10.0, 0.3, _white(0.5))
        body.addSubview_(self._header)

        open_btn = HoverButton.alloc().initWithFrame_baseAlpha_(
            NSMakeRect(_W - _PADX - icon_w, _H - 45, icon_w, 18), 0.82)
        open_btn.setBordered_(False)
        open_btn.setTitle_("↗")
        open_btn.setFont_(NSFont.systemFontOfSize_(13))
        open_btn.setContentTintColor_(_white(0.82))
        open_btn.setTarget_(self)
        open_btn.setAction_("openClicked:")
        open_btn.setHint_callback_("Open on ESPNcricinfo", self._show_hint)
        body.addSubview_(open_btn)
        self._open_btn = open_btn

        refresh = HoverButton.alloc().initWithFrame_baseAlpha_(
            NSMakeRect(_W - _PADX - 2 * icon_w - 2, _H - 45, icon_w, 18), 0.82)
        refresh.setBordered_(False)
        refresh.setTitle_("↻")
        refresh.setFont_(NSFont.systemFontOfSize_(13))
        refresh.setContentTintColor_(_white(0.82))
        refresh.setTarget_(self)
        refresh.setAction_("refreshClicked:")
        refresh.setHint_callback_("Refresh this match", self._show_hint)
        body.addSubview_(refresh)
        self._refresh_btn = refresh

        # --- Team rows (y≈94, 70) ---
        # Layout: name (left) · green bat marker (after the name) · score ·
        # overs (far right). Both score and overs are RIGHT-aligned columns so
        # digits line up on the right. The overs sit flush against the panel's
        # right edge; the score right-aligns to a fixed column just left of the
        # overs. When a row has no overs, set_card widens the score to the right
        # edge so it sits flush right like plain text ("yet to bat", "549/9d").
        self._rows = []
        self._yet_marks = []
        for y in (_H - 74, _H - 99):  # gap below the venue/icons row + big score
            name = self._label(NSMakeRect(left, y, 100, 22), 17, 0.4, _white(1.0))
            bat = self._bat_marker(NSMakeRect(left, y + 3, 17, 17))  # x set per-row
            score = self._label(NSMakeRect(left, y, self._score_right - left, 22),
                                17, 0.5, _white(1.0), align="right", mono=True)
            # Overs right-aligned to the panel edge (x/width set per render in
            # set_card). Its box is shorter and nudged up so the overs text
            # bottom sits on the score text bottom (both fonts draw from the top
            # of their box; a shorter box for the smaller font aligns baselines).
            overs = self._label(
                NSMakeRect(self._score_right, y + 3, 44, 15),
                12, 0.3, _white(0.4), align="right", mono=True)
            # Small dimmed "yet to bat" tag, shown when a team has no score yet.
            yet = self._label(NSMakeRect(left, y + 3, self._right - left, 14),
                              10.0, 0.3, _white(0.35), align="right")
            yet.setStringValue_("yet to bat")
            yet.setHidden_(True)
            body.addSubview_(name)
            body.addSubview_(bat)
            body.addSubview_(score)
            body.addSubview_(overs)
            body.addSubview_(yet)
            self._rows.append((name, bat, score, overs))
            self._yet_marks.append(yet)

        # --- Summary (+ optional interruption note on a 2nd line) ---
        self._summary = self._label(NSMakeRect(left, _H - 125, inner_w, 17),
                                    12.5, 0.4, _rgb(_LIVE))
        body.addSubview_(self._summary)
        # A dimmer 2nd line for an interruption ("Match delayed by rain"), shown
        # only when set_card has a note. Positioned/toggled in set_card; the
        # content below shifts down by _NOTE_H when it's visible.
        self._summary_note = self._label(
            NSMakeRect(left, _H - 125 - self._NOTE_H, inner_w, 15),
            11.5, 0.3, _white(0.5))
        self._summary_note.setHidden_(True)
        body.addSubview_(self._summary_note)

        # --- Recent balls (colored tiles; populated in set_card) ---
        self._balls_container = NSView.alloc().initWithFrame_(
            NSMakeRect(left, _H - 151, inner_w, 22))
        body.addSubview_(self._balls_container)

        # --- Chevron toggle: expands/collapses the batsmen+bowler detail ---
        # A labeled section toggle ("BATSMEN & BOWLER  ▾") rather than a lone
        # arrow, so it reads as an expandable section.
        chev_w = 190.0
        chev = HoverButton.alloc().initWithFrame_baseAlpha_(
            NSMakeRect((_W - chev_w) / 2.0, _H - 176, chev_w, 20), 0.55)
        chev.setBordered_(False)
        chev.setFont_(NSFont.systemFontOfSize_weight_(10.0, 0.5))
        chev.setTitle_("BATSMEN & BOWLER  ▾")
        chev.setContentTintColor_(_white(0.55))
        chev.setAlignment_(Cocoa.NSTextAlignmentCenter)
        chev.setTarget_(self)
        chev.setAction_("chevronClicked:")
        chev.setHint_callback_("Show batsmen & bowler", self._show_hint)
        body.addSubview_(chev)
        self._chevron = chev

        # --- Detail container (batsmen/bowler, grouped; expanded only) ---
        # Flipped so rows lay out top-down; positioned in _resize_for.
        self._detail_container = _FlippedView.alloc().initWithFrame_(
            NSMakeRect(left, _H - self._DETAIL_TOP - 60, inner_w, 60))
        self._detail_container.setHidden_(True)
        body.addSubview_(self._detail_container)
        self._detail_h = 0.0

        # Content in the score area, hidden while loading. Excludes the accent
        # bar, bat markers, chevron and batsmen/bowler — those are conditionally
        # shown by set_card, so we never force them visible.
        self._content_views = [self._header, self._chip, self._summary,
                               self._balls_container,
                               self._refresh_btn, self._open_btn]
        for name, bat, score, overs in self._rows:
            self._content_views += [name, score, overs]

        # Distance from the top of the widget to each view's top edge — used to
        # re-pin content when the widget is resized. Includes the picker, close,
        # chevron, bat markers and yet-to-bat tags — all top-anchored. (The
        # detail container is positioned separately in _resize_for.)
        pinned = (list(self._content_views)
                  + [self._close, self._trigger, self._chevron,
                     self._summary_note]
                  + list(self._yet_marks))
        for _n, bat, _s, _o in self._rows:
            pinned.append(bat)
        self._top_offsets = {}
        for v in pinned:
            f = v.frame()
            self._top_offsets[v] = _H - (f.origin.y + f.size.height)

        self._body = body
        # Loading spinner, re-centered in the score area on every resize.
        self._loader = Loader(body, center_x=_W / 2.0, center_y=_H / 2.0)
        self._recenter_loader(_H)

    @staticmethod
    def _label(rect, size, weight, color, align="left", mono=False) -> NSTextField:
        f = NSTextField.alloc().initWithFrame_(rect)
        f.setBezeled_(False)
        f.setDrawsBackground_(False)
        f.setEditable_(False)
        f.setSelectable_(False)
        # Let clicks pass through the label to the body view underneath.
        f.setRefusesFirstResponder_(True)
        if mono:
            f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight))
        else:
            f.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
        f.setTextColor_(color)
        if align == "right":
            f.setAlignment_(Cocoa.NSTextAlignmentRight)
        elif align == "center":
            f.setAlignment_(Cocoa.NSTextAlignmentCenter)
        f.setStringValue_("")
        return f

    @staticmethod
    def _bat_marker(rect) -> NSImageView:
        """A small green cricket-bat SF Symbol, hidden until a team is batting."""
        iv = NSImageView.alloc().initWithFrame_(rect)
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "figure.cricket", "batting")
        if img is not None:
            img.setTemplate_(True)  # so contentTintColor recolors it
        iv.setImage_(img)
        iv.setContentTintColor_(_rgb(_LIVE))
        iv.setHidden_(True)
        return iv
