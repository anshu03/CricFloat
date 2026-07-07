"""Menu-bar (status-bar) item for CricFloat.

A small icon in the macOS menu bar gives the app a persistent home that's always
reachable — even when the floating widget is hidden or dragged off-screen. Its
menu offers Show/Hide (the toggle), Refresh, and Quit.

Kept as its own NSObject so its menu-action selectors don't collide with the
plain-Python CricFloatApp (PyObjC treats every method on an NSObject subclass as
an Objective-C selector).
"""

from __future__ import annotations

from typing import Callable

import Cocoa
import objc

# NSVariableStatusItemLength == -1: the item sizes to its title/icon.
_VARIABLE_LENGTH = -1.0


def _menu_item(menu, title, target, action, key):
    """Build an NSMenuItem, wire its target/action, append it, and return it.
    Module-level (not a method) so PyObjC doesn't treat it as an ObjC selector."""
    item = Cocoa.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        title, action, key)
    item.setTarget_(target)
    menu.addItem_(item)
    return item


class MenuBar(Cocoa.NSObject):
    """Owns the NSStatusItem and its menu, forwarding clicks to callbacks."""

    def initWithCallbacks_(self, callbacks):  # noqa: N802
        self = objc.super(MenuBar, self).init()
        if self is not None:
            self._on_toggle: Callable[[], None] = callbacks["toggle"]
            self._on_refresh: Callable[[], None] = callbacks["refresh"]
            self._on_quit: Callable[[], None] = callbacks["quit"]
            self._build()
        return self

    def _build(self):
        bar = Cocoa.NSStatusBar.systemStatusBar()
        self._item = bar.statusItemWithLength_(_VARIABLE_LENGTH)
        # A cricket glyph as the menu-bar icon; falls back to text on old macOS.
        button = self._item.button()
        if button is not None:
            button.setTitle_("\U0001F3CF")  # 🏏
            button.setToolTip_("CricFloat — Live Cricket Scores")

        menu = Cocoa.NSMenu.alloc().init()
        # Show/Hide is the toggle; its title is refreshed in set_widget_visible.
        self._toggle_item = _menu_item(menu, "Hide widget", self, "toggleClicked:", "h")
        menu.addItem_(Cocoa.NSMenuItem.separatorItem())
        _menu_item(menu, "Refresh now", self, "refreshClicked:", "r")
        menu.addItem_(Cocoa.NSMenuItem.separatorItem())
        _menu_item(menu, "Quit CricFloat", self, "quitClicked:", "q")
        self._item.setMenu_(menu)

    def set_widget_visible(self, visible: bool):
        """Keep the toggle label in sync with the widget's actual visibility."""
        self._toggle_item.setTitle_("Hide widget" if visible else "Show widget")

    def set_status(self, text: str):
        """Show a compact live score ('WI 90/1') in the menu bar, or just the 🏏
        icon when there's nothing live to show."""
        button = self._item.button()
        if button is None:
            return
        button.setTitle_(f"\U0001F3CF {text}" if text else "\U0001F3CF")

    # ---- menu actions (main thread) ------------------------------------

    def toggleClicked_(self, sender):  # noqa: N802
        self._on_toggle()

    def refreshClicked_(self, sender):  # noqa: N802
        self._on_refresh()

    def quitClicked_(self, sender):  # noqa: N802
        self._on_quit()
