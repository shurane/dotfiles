#!/usr/bin/env python3
"""Turn off DPMS display and listen for wake events."""

import subprocess
import time

from Xlib import X  # ty: ignore[import-not-found]
from Xlib.display import Display  # ty: ignore[import-not-found]

display = Display(":0")
root = display.screen().root
root.grab_pointer(
    True,
    X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask,
    X.GrabModeAsync,
    X.GrabModeAsync,
    0,
    0,
    X.CurrentTime,
)
root.grab_keyboard(True, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)

subprocess.call(["xset", "dpms", "force", "off"])  # noqa: S607
p = subprocess.Popen(["gnome-screensaver-command", "-i"])  # noqa: S607
time.sleep(1)

while True:
    print(display.next_event())
    p.terminate()
    break
