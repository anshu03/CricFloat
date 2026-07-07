"""Run the floating scorecard overlay with live auto-refresh.

    python demo_overlay.py

Shows real data: the dropdown lists current international matches, clicking the
body opens the match on ESPNcricinfo in Chrome, the ✕ hides the widget (bring it
back or quit from the 🏏 menu-bar item). The score auto-refreshes (fast while
live, slow when idle). Ctrl-C also quits.
"""

from __future__ import annotations

import signal

import Cocoa

from cricfloat.app import CricFloatApp


def main() -> None:
    app = Cocoa.NSApplication.sharedApplication()
    app.setActivationPolicy_(Cocoa.NSApplicationActivationPolicyAccessory)

    controller = CricFloatApp()
    controller.start()
    controller.overlay.show()

    signal.signal(signal.SIGINT, lambda *_: Cocoa.NSApp().terminate_(None))
    print("Overlay shown. Auto-refreshing. Click to open in Chrome, ✕ to close.")
    app.run()


if __name__ == "__main__":
    main()
