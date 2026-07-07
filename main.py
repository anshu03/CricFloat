"""CricFloat app entry point (used by the .app bundle and for `python main.py`).

Launches the floating scorecard overlay as a menu-bar accessory app: no Dock
icon, a 🏏 status-bar item, and the always-on-top widget. See demo_overlay.py for
the terminal-oriented dev launcher (identical behaviour, extra print/Ctrl-C).
"""

from __future__ import annotations

import signal

import Cocoa

from cricfloat.app import CricFloatApp


def main() -> None:
    app = Cocoa.NSApplication.sharedApplication()
    # Accessory: no Dock icon, no app menu — lives in the menu bar + overlay.
    app.setActivationPolicy_(Cocoa.NSApplicationActivationPolicyAccessory)

    controller = CricFloatApp()
    controller.start()
    controller.overlay.show()

    # Allow Ctrl-C to quit when launched from a terminal (no-op inside a .app).
    signal.signal(signal.SIGINT, lambda *_: Cocoa.NSApp().terminate_(None))
    app.run()


if __name__ == "__main__":
    main()
