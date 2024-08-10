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
        help="Supported commands: `evdev`, `hidraw`, `gamescope`",
    )
    args = parser.parse_args()

    cmds = args.command
    try:
        match cmds[0]:
            case "evdev":
                from .dev import evdev

                evdev(cmds[1] if len(cmds) > 1 else None)
            case "hidraw":
                from .dev import hidraw

                if len(cmds) > 1:
                    hidraw(*cmds[1:])
                else:
                    hidraw(None)
            case "gamescope":
                from .gs import gamescope_debug

                gamescope_debug(cmds[1:])
            case _:
                print(f"Command `{cmds[0]}` not supported.")
    except KeyboardInterrupt:
        pass
