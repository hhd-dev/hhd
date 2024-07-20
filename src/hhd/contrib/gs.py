from Xlib.display import Display

from hhd.plugins.overlay.x11 import (
    QamHandlerGamescope,
    get_gamescope_displays,
    get_overlay_display,
    print_debug,
)


def gamescope_debug(args: list[str]):
    if "qam" in args or "menu" in args:
        force_disp = None
        for arg in args:
            if arg.startswith(":"):
                force_disp = arg

        open_menu = "menu" in args
        win = "menu" if open_menu else "QAM"
        print(f"Opening Steam {win}.")
        c = QamHandlerGamescope(force_disp=force_disp, compat_send=False)
        success = c(open_menu)
        c.close()
        if not success:
            import sys

            print(f"Error, could not open {win}.")
            sys.exit(1)
        return

    if not args or not args[0].startswith(":"):
        ds = get_gamescope_displays()
        print(f"Gamescope displays found: {str(ds)}")
        d = get_overlay_display(ds)
        if not d:
            print(f"Overlay display not found, exitting...")
            return
        d, name = d
    else:
        did = args[0]
        name = did
        d = Display(did)

    print(f"Overlay display is '{name}'")

    print("\nDebug Data:")
    print_debug(d, args)
