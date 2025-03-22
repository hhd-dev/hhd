import argparse
import sys
import time
from .ctl import get_state, set_state, unroll_dict

SOCKET_UNIX = "/run/hhd/api"
USAGE = """
hhd.steamos [-h] {steamos-select-branch,steamos-update} [--fallback] [keys ...]

Handheld Daemon steamos polkit stub
Allows mimicking the polkit behavior of SteamOS to perform updates, etc.
For specifics, refer to SteamOS. The --fallback option is provided which will
return 20 if handheld daemon cannot update the system. In this case, you can
use the legacy fallback to update the system.

Commands:
    steamos-select-branch: Select a branch that running steamos-update will update to.
        Aliased to steamos-branch-select. Options are: rel, rc, beta, main, bc, -l, -c.
    steamos-update: Perform an update. 

"""


ALL = {
    "set_state": set_state,
    "get_state": get_state,
}

BRANCH_MAP = {
    "rel": "stable",
    "beta": "testing",
    "preview": "testing",
    "rc": "testing",
    "bc": "unstable",
    "pc": "unstable",
    "main": "unstable",
}

FALLBACK_CODE = 20


def _select_branch(fallback, opts):
    branch = "stable"
    try:
        state = unroll_dict(get_state())
        stage = state.get("updates.bootc.steamos-update", None)
        # print(f"Stage: {stage}", file=sys.stderr)
        incompatible = stage is None or stage == "incompatible"

        img = state.get("updates.bootc.image", None).split(":")[-1]
        assert img is not None
        for k, v in BRANCH_MAP.items():
            if img.startswith(v):
                branch = k
                break
    except Exception as e:
        incompatible = True
        print(f"Error: {e}", file=sys.stderr)
    if incompatible and fallback:
        return FALLBACK_CODE

    if "-c" in opts:
        print(branch)
        return 0
    if "-l" in opts:
        for v in BRANCH_MAP.keys():
            print(v)
        return 0

    if not opts:
        print("No option provided", file=sys.stderr)
        return 0

    if incompatible:
        print("Incompatible state", file=sys.stderr)
        return 0

    if not opts:
        return 0

    target = opts[0]
    if target == branch:
        return 0

    target_os = None
    for k, v in BRANCH_MAP.items():
        if target == k:
            target_os = v
            break

    if target_os is None:
        print(f"Invalid branch: {target}", file=sys.stderr)
        return 0
    
    print("Ignoring request to rebase from SteamOS", file=sys.stderr)
    return 0


def _update(fallback, opts):
    if "--supports-duplicate-detection" in opts:
        return 0

    check = "check" in opts

    # Check if there is an update
    try:
        if unroll_dict(get_state()).get("updates.bootc.steamos-update", None) in (
            "incompatible",
            None,
        ):
            print("Incompatible state", file=sys.stderr)
            return FALLBACK_CODE if fallback else 0

        val = unroll_dict(set_state({"updates.bootc.steamos-update": "check"})).get(
            "updates.bootc.steamos-update", None
        )
        while val == "check":
            val = unroll_dict(get_state(poll=True)).get(
                "updates.bootc.steamos-update", None
            )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if fallback:
            return FALLBACK_CODE
        return 1

    if val != "has-update" and not (val and val.endswith("%")):
        print(f"No updates available ({val})", file=sys.stderr)
        return 7
    elif check:
        print(f"Updates available ({val})", file=sys.stderr)
        return 0

    # Otherwise apply, bootc does not need separate steps
    if not val or not val.endswith("%"):
        val = unroll_dict(set_state({"updates.bootc.steamos-update": "apply"})).get(
            "updates.bootc.steamos-update", None
        )

    curr = 0.2
    while not val or "%" in val or val == "apply":
        if val and val.endswith("%"):
            next = float(val[:-1])
            while curr < next:
                # print(f"\r\033[K\r{curr:.2f}% 1m1s", end="")
                print(f"\r{curr:.2f}%", end="")
                sys.stdout.flush()
                curr += min(5, next - curr)
                time.sleep(0.2)

        val = unroll_dict(get_state(poll=True)).get(
            "updates.bootc.steamos-update", None
        )

    if val != "updated":
        return 1
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
            case "steamos-branch-select" | "steamos-select-branch":
                v = _select_branch(fallback, opts)
            case "steamos-update":
                v = _update(fallback, opts)
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
