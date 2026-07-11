import argparse
import sys
import time
from .ctl import get_state, set_state, unroll_dict, send_event

SOCKET_UNIX = "/run/hhd/api"
USAGE = """
hhd.steamos [-h] {steamos-tdp,steamos-gpu} [--fallback] [keys ...]

Handheld Daemon steamos polkit stub
Used for steamos-manager to forward tdp to the steam client.
"""

ALL = {
    "set_state": set_state,
    "get_state": get_state,
    "send_event": send_event,
}


def _tdp(opts):
    # Return statuses:
    # 1: generic error, fallback to steamos manager
    # 2: conflict with another application, disable all controls
    # 3: failed to set tdp, ignore and retry

    if not opts:
        print(
            "Either provide a tdp value (e.g. 15) or get for the current limits",
            file=sys.stderr,
        )
        return -1

    try:
        state = unroll_dict(get_state())
        status = state.get("hhd.steamos.tdp_status", None)
        min = state.get("hhd.steamos.tdp_min", None)
        max = state.get("hhd.steamos.tdp_max", None)
        was_set = state.get("hhd.steamos.tdp_set", None)
        default = state.get("hhd.steamos.tdp_default", None)

        if status == "conflict":
            print(
                "TDP management conflict with another application. Disable controls.",
                file=sys.stderr,
            )
            return 2
        elif status != "enabled":
            print(
                "TDP management disabled. Fallback to steamos manager.", file=sys.stderr
            )
            return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not max:
        return 1

    if opts[0] == "get":
        print(f"{min} {max} {default}")
        return 0

    if str(max) == opts[0] and not was_set:
        # Skip setting max_tdp if tdp was not
        # set previously
        return 0

    try:
        send_event(
            {
                "type": "tdp",
                "tdp": int(opts[0]),
            }
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3

    return 0


def _gpu(opts):
    # Return statuses:
    # 1: generic error, fallback to steamos manager
    # 2: conflict with another application, disable all controls
    # 3: failed to set tdp, ignore and retry
    # 5: retry a few times and return 1

    if not opts:
        print(
            "Either provide a tdp value (e.g. 15) or get for the current limits",
            file=sys.stderr,
        )
        return -1

    try:
        state = unroll_dict(get_state())
        min = state.get("hhd.steamos.gpu_min", None)
        max = state.get("hhd.steamos.gpu_max", None)
        status = state.get("hhd.steamos.gpu_status", None)
        was_set = state.get("hhd.steamos.gpu_set", None)

        if status == "conflict":
            print(
                "GPU management conflict with another application. Disable controls.",
                file=sys.stderr,
            )
            return 2
        elif status != "enabled":
            print(
                "GPU management disabled. Fallback to steamos manager.", file=sys.stderr
            )
            return 1
        if min is None or max is None:
            print(
                "GPU slider is not available. Fallback to steamos manager.",
                file=sys.stderr,
            )
            return 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if opts[0] == "get":
        print(f"{min} {max}")
        return 0

    actual_max = max

    if opts[0] != "clear":
        try:
            min = int(opts[0])
        except ValueError:
            min = None

        try:
            max = int(opts[1])
        except IndexError:
            max = min
            min = None
        except ValueError:
            max = None
    else:
        min = max = None

    if str(max) == str(actual_max):
        if not was_set:
            # Skip setting gpu if tdp was not
            # set previously
            return 0
        else:
            # Clear gpu settings
            min = max = None

    try:
        send_event(
            {
                "type": "gpu",
                "min": min,
                "max": max,
            }
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3

    return 0


def main():
    fallback = False
    try:
        if "--help" in sys.argv or "-h" in sys.argv or len(sys.argv) < 2:
            print(USAGE)
            sys.exit(0)

        fallback = "--fallback" in sys.argv
        cmd = sys.argv[1]

        opts = [v for v in sys.argv[2:] if v != "--fallback"]
        match cmd:
            case "steamos-tdp":
                v = _tdp(opts)
            case "steamos-gpu":
                v = _gpu(opts)
            case _:
                print(f"Invalid command: '{cmd}'")
                v = -1

        if v is not None:
            sys.exit(v)

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
