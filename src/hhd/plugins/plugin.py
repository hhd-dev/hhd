import getpass
import logging
import os
import subprocess
from typing import Any, Literal, Mapping, NamedTuple, Protocol, Sequence, TypedDict

from threading import Lock

from hhd.controller import Axis, Button, Configuration, ControllerEmitter, SpecialEvent

from .conf import Config
from .settings import HHDSettings

logger = logging.getLogger(__name__)

STEAM_PID = "~/.steam/steam.pid"
STEAM_EXE = "~/.steam/root/ubuntu12_32/steam"


class Context(NamedTuple):
    euid: int = 0
    egid: int = 0
    uid: int = 0
    gid: int = 0
    name: str = "root"
    # scratch: str = ""


class SettingsEvent(TypedDict):
    type: Literal["settings"]


class PowerEvent(TypedDict):
    type: Literal["acpi"]
    event: Literal["ac", "dc", "tdp", "battery"]


class TdpEvent(TypedDict):
    type: Literal["tdp"]
    tdp: int | None


class ProfileEvent(TypedDict):
    type: Literal["profile"]
    name: str
    config: Config | None


class ApplyEvent(TypedDict):
    type: Literal["apply"]
    name: str


class ConfigEvent(TypedDict):
    type: Literal["state"]
    config: Config


class EnergyEvent(TypedDict):
    type: Literal["ppd", "energy"]
    status: Literal["power", "balanced", "performance"]


class InputEvent(TypedDict):
    type: Literal["input"]
    controller_id: int

    btn_state: Mapping[Button, bool]
    axis_state: Mapping[Axis, bool]
    conf_state: Mapping[Configuration, Any]


Event = (
    ConfigEvent
    | InputEvent
    | ProfileEvent
    | ApplyEvent
    | SettingsEvent
    | SpecialEvent
    | PowerEvent
    | TdpEvent
    | EnergyEvent
)


class Emitter(ControllerEmitter):
    def __init__(self, ctx=None, info=None) -> None:
        if info is None:
            info = Config()
        self.info = info
        self.data = {}
        self.images = {}
        super().__init__(ctx)

    def __call__(self, event: Event | Sequence[Event]) -> None:
        pass

    def set_gamedata(
        self, data: dict[str, dict[str, str]], images: dict[str, dict[str, str]]
    ) -> None:
        with self.intercept_lock:
            self.data = data
            self.images = images

    def get_gamedata(self, game: str | None) -> dict[str, str] | None:
        if not game:
            return None
        with self.intercept_lock:
            return self.data.get(game, None)

    def get_image(self, game: str, icon: str) -> str | None:
        with self.intercept_lock:
            return self.images.get(game, {}).get(icon, None)


class HHDPlugin:
    name: str
    priority: int
    log: str

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        pass

    def settings(self) -> HHDSettings:
        return {}

    def validate(self, tags: Sequence[str], config: Any, value: Any):
        return False

    def prepare(self, conf: Config):
        pass

    def update(self, conf: Config):
        pass

    def notify(self, events: Sequence[Event]):
        pass

    def close(self):
        pass


class HHDAutodetect(Protocol):
    def __call__(self, existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
        raise NotImplementedError()


class HHDLocale(TypedDict):
    dir: str
    domain: str
    priority: int


class HHDLocaleRegister(Protocol):
    def __call__(self) -> Sequence[HHDLocale]:
        raise NotImplementedError()


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

        user = user.replace("\\x2", "-")

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


def get_gid(uid: int):
    return int(
        subprocess.run(
            ["id", "-g", str(uid)], capture_output=True, check=True
        ).stdout.decode()
    )


def switch_priviledge(nuid: int) -> tuple[int, int]:
    uid = os.geteuid()
    gid = os.getegid()

    ngid = get_gid(nuid)
    if uid != nuid or gid != ngid:
        os.seteuid(0)

    if gid != ngid:
        os.setegid(ngid)
    if uid != nuid:
        os.seteuid(nuid)

    return uid, gid


def save_priviledge() -> tuple[int, int]:
    uid = os.geteuid()
    gid = os.getegid()

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


def get_steam_location(gamepadui: bool = True):
    for p in os.listdir("/proc"):
        try:
            if not p.isdigit():
                continue
            with open(f"/proc/{p}/cmdline", "rb") as f:
                cmd = f.read().split(b"\0")

            steamp = False
            for c in cmd[:2]:
                if c.endswith(b"/steam"):
                    steamp = c
                    break
            if not steamp:
                continue
            if gamepadui and b"-gamepadui" not in cmd:
                continue

            # We need the executable for shortpress to work, if it ends in .sh
            # it will not. Moreover, flatpak resolving requires the ps path.
            uid = os.stat(f"/proc/{p}/").st_uid
            return expanduser(STEAM_EXE, uid), int(p), uid
        except Exception:
            pass
    return None, None, None

_run_lock = Lock()
_running = False


def refresh_is_steam_running():
    global _running

    with _run_lock:
        _running = get_steam_location()[0] is not None


def is_steam_gamepad_running(gamepadui: bool = True) -> bool:
    with _run_lock:
        return _running


def run_steam_command(command: str):
    steam, _, uid = get_steam_location(False)

    if steam is None or uid is None:
        logger.error("Steam is not running or could not be found.")
        return False

    try:
        gid = get_gid(uid)
        result = subprocess.run(
            [steam, "-ifrunning", command],
            check=False,
            user=uid,
            group=gid,
            env={
                "HOME": expanduser("~", uid),
            },
        )

        logger.info(
            f"Running steam command `{[steam, "-ifrunning", command]}` with uid={uid} gid={gid} result: {result}"
        )

        return result.returncode == 0
    except Exception as e:
        logger.error(f"Received error when running steam command `{command}`\n{e}")
    return False


def open_steam_kbd(open: bool = True):
    return run_steam_command(f"steam://{'open' if open else 'close'}/keyboard")


def freeze_steam(freeze: bool):
    pid = None
    try:
        import signal

        _, pid, _ = get_steam_location(False)

        if pid is None:
            return False

        os.kill(
            int(pid),
            signal.SIGSTOP if freeze else signal.SIGCONT,
        )
        return True
    except Exception:
        import traceback

        traceback.print_exc()
        return False
