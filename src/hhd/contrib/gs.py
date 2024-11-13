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
        args = args[1:]
    print(f"Overlay display is '{name}'")

    cmd_sent = False
    if args:
        for arg in args:
            if "=" in arg:
                from Xlib import Xatom

                atom, val = arg.split("=", 1)

                print(f"Setting {atom} to {val}")
                d.screen().root.change_property(
                    d.get_atom(atom), Xatom.CARDINAL, 32, [int(val)]
                )
                cmd_sent = True

    if cmd_sent:
        d.flush()
    else:
        print("\nDebug Data:")
        print_debug(d, args)
