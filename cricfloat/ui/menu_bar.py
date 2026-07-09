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
            self._on_size: Callable[[str], None] = callbacks.get("size", lambda _p: None)
            self._size_items: dict = {}   # preset name -> NSMenuItem (for checkmarks)
            self._size_preset = callbacks.get("size_preset", "default")
            self._build()
        return self

    def _build(self):
        # The status item is retained by this (retained) MenuBar object; if its
        # creation ever fails on some Mac, don't let that take down app startup —
        # the app still has the widget + the ⌘Q app-menu quit path.
        self._item = None
        self._toggle_item = None
        try:
            bar = Cocoa.NSStatusBar.systemStatusBar()
            self._item = bar.statusItemWithLength_(_VARIABLE_LENGTH)
            # Keep the item pinned to the menu bar (not user-hideable), so it
            # doesn't silently vanish behind the notch / overflow with no way to
            # get it back.
            if hasattr(self._item, "setVisible_"):
                self._item.setVisible_(True)
            if hasattr(self._item, "behavior") and hasattr(self._item, "setBehavior_"):
                self._item.setBehavior_(0)  # not removal/terminate-on-removal

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

            # Size submenu (Default / Large) with a checkmark on the current
            # preset.
            size_item = Cocoa.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Size", None, "")
            size_menu = Cocoa.NSMenu.alloc().init()
            for name in ("default", "large"):
                it = _menu_item(size_menu, name.capitalize(), self, "sizeClicked:", "")
                it.setRepresentedObject_(name)
                it.setState_(1 if name == self._size_preset else 0)
                self._size_items[name] = it
            size_item.setSubmenu_(size_menu)
            menu.addItem_(size_item)

            menu.addItem_(Cocoa.NSMenuItem.separatorItem())
            _menu_item(menu, "Quit CricFloat", self, "quitClicked:", "q")
            self._item.setMenu_(menu)
        except Exception:
            # Menu bar unavailable — the app still works via the widget and ⌘Q.
            self._item = None

    def set_widget_visible(self, visible: bool):
        """Keep the toggle label in sync with the widget's actual visibility."""
        if self._toggle_item is not None:
            self._toggle_item.setTitle_("Hide widget" if visible else "Show widget")

    def set_status(self, text: str):
        """Show a compact live score ('WI 90/1') in the menu bar, or just the 🏏
        icon when there's nothing live to show."""
        if self._item is None:
            return
        button = self._item.button()
        if button is None:
            return
        button.setTitle_(f"\U0001F3CF {text}" if text else "\U0001F3CF")

    def set_size(self, preset: str):
        """Move the Size submenu checkmark to `preset`."""
        self._size_preset = preset
        for name, item in self._size_items.items():
            item.setState_(1 if name == preset else 0)

    # ---- menu actions (main thread) ------------------------------------

    def toggleClicked_(self, sender):  # noqa: N802
        self._on_toggle()

    def refreshClicked_(self, sender):  # noqa: N802
        self._on_refresh()

    def sizeClicked_(self, sender):  # noqa: N802
        self._on_size(sender.representedObject())

    def quitClicked_(self, sender):  # noqa: N802
        self._on_quit()
