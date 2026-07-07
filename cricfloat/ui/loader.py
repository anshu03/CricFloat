"""A standard indeterminate spinner shown over the widget while a match's data
is being fetched (initial load, or after selecting a new match). Never shown
during routine refreshes."""

from __future__ import annotations

import Cocoa
from Cocoa import NSMakePoint, NSMakeRect, NSProgressIndicator, NSView

_SIZE = 20.0
NSProgressIndicatorStyleSpinning = 1


class Loader:
    """Owns a native spinning progress indicator; call show()/hide()."""

    def __init__(self, parent: NSView, center_x: float, center_y: float) -> None:
        frame = NSMakeRect(center_x - _SIZE / 2.0, center_y - _SIZE / 2.0,
                           _SIZE, _SIZE)
        spinner = NSProgressIndicator.alloc().initWithFrame_(frame)
        spinner.setStyle_(NSProgressIndicatorStyleSpinning)
        spinner.setIndeterminate_(True)
        spinner.setControlSize_(Cocoa.NSControlSizeSmall)
        spinner.setDisplayedWhenStopped_(False)
        # Light appearance so the spinner reads on the dark panel.
        appr = Cocoa.NSAppearance.appearanceNamed_("NSAppearanceNameVibrantDark")
        if appr is not None:
            spinner.setAppearance_(appr)
        parent.addSubview_(spinner)
        self._spinner = spinner

    def set_center(self, center_x: float, center_y: float) -> None:
        self._spinner.setFrameOrigin_(
            NSMakePoint(center_x - _SIZE / 2.0, center_y - _SIZE / 2.0))

    def show(self) -> None:
        self._spinner.startAnimation_(None)

    def hide(self) -> None:
        self._spinner.stopAnimation_(None)
