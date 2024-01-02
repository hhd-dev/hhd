import logging
import os
import subprocess
from typing import NamedTuple
import getpass

from hhd.plugins import Context

logger = logging.getLogger(__name__)


def get_context(user: str | None) -> Context | None:
    try:
        uid = os.getuid()
        gid = os.getgid()

        if not user:
            if not uid:
                print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                print(
                    "Running as root without a specified user (`--user`). Configs will be placed at `/root/.config`."
                )
                print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            return Context(uid, gid, uid, gid, getpass.getuser())

        euid = int(
            subprocess.run(
                ["id", "-u", user], capture_output=True, check=True
            ).stdout.decode()
        )
        egid = int(
            subprocess.run(
                ["id", "-g", user], capture_output=True, check=True
            ).stdout.decode()
        )

        if (uid or gid) and (uid != euid or gid != egid):
            print(
                f"The user specified with --user is not the user this process was started with."
            )
            return None

        return Context(euid, egid, uid, gid, user)
    except subprocess.CalledProcessError as e:
        print(f"Getting the user uid/gid returned an error:\n{e.stderr.decode()}")
        return None
    except Exception as e:
        print(f"Failed getting permissions with error:\n{e}")
        return None


def switch_priviledge(p: Context, escalate=False):
    uid = os.geteuid()
    gid = os.getegid()

    if escalate:
        os.seteuid(p.uid)
        os.setegid(p.gid)
    else:
        os.setegid(p.egid)
        os.seteuid(p.euid)

    return uid, gid


def restore_priviledge(old: tuple[int, int]):
    uid, gid = old
    # Try writing group first in case of root
    # and fail silently
    try:
        os.setegid(gid)
    except Exception:
        pass
    os.seteuid(uid)
    os.setegid(gid)
    pass


def expanduser(path: str, user: int | str | Context | None = None):
    """Expand ~ and ~user constructions.  If user or $HOME is unknown,
    do nothing.

    Modified from the python implementation to support using the target userid/user."""

    path = os.fspath(path)

    if not path.startswith("~"):
        return path

    i = path.find("/", 1)
    if i < 0:
        i = len(path)
    if i == 1:
        if "HOME" in os.environ and not user:
            # Fallback to environ only if user not set
            userhome = os.environ["HOME"]
        else:
            try:
                import pwd
            except ImportError:
                # pwd module unavailable, return path unchanged
                return path
            try:
                if not user:
                    userhome = pwd.getpwuid(os.getuid()).pw_dir
                elif isinstance(user, int):
                    userhome = pwd.getpwuid(user).pw_dir
                elif isinstance(user, Context):
                    userhome = pwd.getpwuid(user.euid).pw_dir
                else:
                    userhome = pwd.getpwnam(user).pw_dir
            except KeyError:
                # bpo-10496: if the current user identifier doesn't exist in the
                # password database, return the path unchanged
                return path
    else:
        try:
            import pwd
        except ImportError:
            # pwd module unavailable, return path unchanged
            return path
        name = path[1:i]
        try:
            pwent = pwd.getpwnam(name)
        except KeyError:
            # bpo-10496: if the user name from the path doesn't exist in the
            # password database, return the path unchanged
            return path
        userhome = pwent.pw_dir

    root = "/"
    userhome = userhome.rstrip(root)
    return (userhome + path[i:]) or root


def fix_perms(fn: str, ctx: Context):
    os.chown(fn, ctx.euid, ctx.egid)
