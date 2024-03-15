import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="HHD: Handheld Daemon contribution helper scripts",
        description="Scripts to automate the capture of events, etc.",
    )
    parser.add_argument(
        "command",
        nargs="+",
        default=[],
        help="Supported commands: `evdev`, `hidraw`",
    )
    args = parser.parse_args()

    try:
        match c := args.command[0]:
            case "evdev":
                from .dev import evdev

                evdev()
            case "hidraw":
                from .dev import hidraw

                hidraw()
            case "gamescope":
                from .gs import gamescope_debug

                gamescope_debug()
            case _:
                print(f"Command `{c}` not supported.")
    except KeyboardInterrupt:
        pass

