from Xlib.display import Display

from hhd.plugins.overlay.x11 import (
    get_gamescope_displays,
    get_overlay_display,
    print_debug,
)


def gamescope_debug(did: str | None):
    if not did:
        ds = get_gamescope_displays()
        print(f"Gamescope displays found: {str(ds)}")
        d = get_overlay_display(ds)
        if not d:
            print(f"Overlay display not found, exitting...")
            return
        d, name = d
    else:
        name = did
        d = Display(did)

    print(f"Overlay display is '{name}'")

    print("\nDebug Data:")
    print_debug(d)
