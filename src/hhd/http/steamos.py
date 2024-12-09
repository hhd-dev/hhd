import argparse
import sys
from .ctl import get_state, set_state, unroll_dict

SOCKET_UNIX = "/run/hhd/api"
USAGE = """
hhd.steamos [-h] {steamos-branch-select,steamos-update} [--fallback] [keys ...]

Handheld Daemon steamos polkit stub
Allows mimicking the polkit behavior of SteamOS to perform updates, etc.
For specifics, refer to SteamOS. The --fallback option is provided which will
return 20 if handheld daemon cannot update the system. In this case, you can
use the legacy fallback to update the system.

Commands:
    steamos-branch-select: Select a branch that running steamos-update will update to.
    steamos-update: Perform an update. 

"""


ALL = {
    "set_state": set_state,
    "get_state": get_state,
}

BRANCH_MAP = {
    "stable": "stable",
    "testing": "beta",
    "unstable": "main",
}

FALLBACK_CODE = 20


def _select_branch(fallback, opts):
    branch = "stable"
    try:
        state = unroll_dict(get_state())
        stage = state.get("updates.bootc.steamos-update", None)
        # print(f"Stage: {stage}", file=sys.stderr)
        incompatible = stage is None or stage == "incompatible"

        branch = state.get("updates.bootc.steamos-target", None)
        if not branch:
            img = state.get("updates.bootc.image", None)
            assert img is not None
            for k, v in BRANCH_MAP.items():
                if k in img:
                    branch = v
                    break
    except Exception as e:
        incompatible = True
        print(f"Error: {e}", file=sys.stderr)
    if incompatible and fallback:
        return FALLBACK_CODE

    if not opts:
        print("No option provided", file=sys.stderr)
        return 0

    if incompatible:
        print("Incompatible state", file=sys.stderr)
        return 0

    if "-c" in opts:
        return branch
    if "-l" in opts:
        for v in BRANCH_MAP.values():
            print(v)
        return 0

    if not opts:
        return 0

    target = opts[0]
    if target == branch:
        return 0

    target_os = None
    for k, v in BRANCH_MAP.items():
        if target == v:
            target_os = k
            break

    if target_os is None:
        print(f"Invalid branch: {target}", file=sys.stderr)
        return 0

    print(f"Setting target to {target_os}", file=sys.stderr)
    set_state({"updates.bootc.steamos-target": target_os})
    return 0


def _update(fallback, opts):
    if "--supports-duplicate-detection" in opts:
        return 0

    check = "check" in opts

    # Check if there is an update
    set_state({"updates.bootc.steamos-update": "check"})
    val = unroll_dict(set_state({"updates.bootc.steamos-update": "check"})).get(
        "updates.bootc.steamos-update", None
    )
    while val == "check":
        val = unroll_dict(get_state(poll=True)).get(
            "updates.bootc.steamos-update", None
        )

    if val != "has-update" and not (val and val.startswith("%")):
        print(f"No updates available ({val})", file=sys.stderr)
        return 7
    elif check:
        print(f"Updates available ({val})", file=sys.stderr)
        return 0

    # Otherwise apply, bootc does not need separate steps
    val = unroll_dict(set_state({"updates.bootc.steamos-update": "apply"})).get(
        "updates.bootc.steamos-update", None
    )
    while not val or "%" in val or val == "apply":
        if not val or val == "apply":
            print("0%")
        else:
            print(val)
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

        match cmd:
            case "steamos-branch-select":
                v = _select_branch(fallback, sys.argv[2:])
            case "steamos-update":
                v = _update(fallback, sys.argv[2:])
            case _:
                print(f"Invalid command: '{cmd}'")
                v = -1

        if v is not None:
            sys.exit(v)

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        raise e
        if fallback:
            sys.exit(20)
        sys.exit(1)


if __name__ == "__main__":
    main()
