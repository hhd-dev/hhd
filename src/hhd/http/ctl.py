import argparse
import json
import logging
import socket
import sys
from http.client import HTTPConnection

logger = logging.getLogger(__name__)

SOCKET_UNIX = "/run/hhd/api"
USAGE = """
hhdctl [-h] [--sep SEP] [--values] {get,set,poll,track} [keys ...]

Handheld Daemon CLI
This CLI is used to interact with  Handheld Daemon (hhd) via its API. It requires 
root access to connect to the UNIX socket at /run/hhd/api. The current version 
allows for querying the state of Handheld Daemon and updating its values.

Commands:
    get: Get the current state of Handheld Daemon. If keys are provided, only 
        those keys are returned. Returned as KEY=VALUE pairs separated by \\n.
    set: Update values in the current state. This call blocks until values are
        updated and returns the new values. WARNING: the new values might not
        be the ones that were set if they were rejected. Use None to remove a key.
    poll: Same as get but will wait for the next Handheld Daemon event loop to
        return. The loop runs every 2s or whenever an event is received.
    track: Continuously track the provided values. Same as calling get and then 
        poll repeatedly. The separator between updates can be changed with --sep. 
        Default is \\n. track will print the values even if they did not change.

Examples:
    hhdctl get
    hhdctl get/track/poll rgb.handheld.mode.mode
    hhdctl set rgb.handheld.mode.mode=oxp
    # For a single value, --values and --sep='' can be used to return the value
    hhdctl get rgb.handheld.mode.mode --values --sep=''
"""


def _unroll_dict(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            if prefix:
                k = f"{prefix}.{k}"
            yield from _unroll_dict(v, k)
    else:
        yield prefix, d


def unroll_dict(d):
    return dict(_unroll_dict(d))


class UnixConnection(HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(SOCKET_UNIX)


def _request(*args, **kwargs):
    con = UnixConnection(SOCKET_UNIX)
    con.request(*args, **kwargs)
    return con.getresponse()


def _get_state(poll: bool = False):
    return _request("GET", f"/api/v1/state{'?poll' if poll else ''}")


def _set_state(state):
    return _request("POST", f"/api/v1/state", body=json.dumps(state))


def _get(keys, poll: bool = False, state=None, values: bool = False):
    if state is not None:
        state = _set_state(state)
    else:
        state = _get_state(poll)

    # Drop values in keys for ease of use
    if keys:
        keys = [k.split("=", 1)[0] for k in keys]

    if state.status != 200:
        logger.error(f"Failed to get state with status: {state.status}")
        return 2

    out = ""
    data = unroll_dict(json.loads(state.read()))
    err = 0
    for k in keys or data:
        if k not in data or data[k] is None:
            # Eat none values as the purge happens after restart
            logger.error(f"Key {k} not found in state")
            err = 3
            continue
        else:
            vr = data[k]

        if isinstance(vr, bool):
            v = "true" if vr else "false"
        elif isinstance(vr, str):
            # Escape newlines
            v = vr.replace("\n", "\\n").replace("\t", "\\t")
        else:
            v = vr

        if values:
            out += f"{v}\n"
        else:
            out += f"{k}={v}\n"

    sys.stdout.write(out)
    sys.stdout.flush()
    return err


def _track(keys, sep, values):
    poll = False
    while True:
        _get(keys, poll=poll, values=values)
        sys.stdout.write(sep)
        sys.stdout.flush()
        poll = True


def _set(keys, values):
    if not keys:
        logger.error("No keys provided to set")
        return 1

    state = {}
    for key in keys:
        try:
            k, vr = key.split("=", 1)
        except ValueError:
            logger.error(f"Invalid KEY=VALUE: {key}")
            return 1

        if vr.lower() in ["true", "false"]:
            v = vr.lower() == "true"
        elif vr.lower() == "none":
            v = None
        elif vr.isdigit():
            v = int(vr)
        elif vr.isnumeric():
            v = float(vr)
        else:
            v = vr

        state[k] = v

    return _get(keys, state=state, values=values)


def _main():
    logging.basicConfig(
        level=logging.DEBUG, stream=sys.stderr, format="%(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(
        usage=USAGE,
        prog="hhdctl",
    )

    parser.add_argument(
        "command", help="Command to execute", choices=["get", "set", "poll", "track"]
    )
    parser.add_argument(
        "keys",
        help="Key(s) to get/set/track. Format: KEY=VAL for set and KEY for get, track. If not provided, get and track return all parameters.",
        nargs="*",
    )
    parser.add_argument(
        "--sep",
        help="Separator for updates in track",
        default="\n",
    )
    parser.add_argument(
        "--values",
        help="Hide the KEY= part in the response. The return value is 3 if a value is missing.",
        action="store_true",
        default=False,
    )

    args = parser.parse_args()

    match args.command:
        case "get":
            v = _get(args.keys, values=args.values)
        case "set":
            v = _set(args.keys, args.values)
        case "track":
            v = _track(args.keys, args.sep, args.values)
        case "poll":
            v = _get(args.keys, poll=True, values=args.values)
        case _:
            logger.error(f"Invalid command: '{args.command}'")
            v = -1

    if v is not None:
        sys.exit(v)


def set_state(state):
    res = _set_state(state)
    if res.status != 200:
        raise Exception(f"Failed to set state with status: {res.status}")
    return json.loads(res.read())


def get_state(poll: bool = False):
    res = _get_state(poll)
    if res.status != 200:
        raise Exception(f"Failed to get state with status: {res.status}")
    return json.loads(res.read())


def main():
    try:
        _main()
    except KeyboardInterrupt:
        sys.exit(0)
    except PermissionError:
        logger.error(
            "Permission denied when trying to connect to the UNIX socket. Are you running as root?"
        )
        sys.exit(1)


ALL = {
    "set_state": set_state,
    "get_state": get_state,
    "unroll_dict": unroll_dict,
    "main": main,
}


if __name__ == "__main__":
    main()
