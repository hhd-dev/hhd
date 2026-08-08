import logging
import os
import pwd
import re
import stat
import tempfile

logger = logging.getLogger(__name__)

LOGIN_DEFS_PATH = "/etc/login.defs"
PLASMALOGIN_PATH = "/etc/plasmalogin.conf"

DEFAULT_UID_MIN = 1000
DEFAULT_UID_MAX = 60000

AUTOLOGIN_HEADER = "[Autologin]"
AUTOLOGIN_SESSION = "Session=gamemode.desktop"


def get_uid_bounds(path: str = LOGIN_DEFS_PATH) -> tuple[int, int]:
    uid_min = DEFAULT_UID_MIN
    uid_max = DEFAULT_UID_MAX

    try:
        with open(path, "r") as f:
            for line in f:
                fields = line.split()
                if len(fields) < 2 or fields[0].startswith("#"):
                    continue
                if fields[0] == "UID_MIN":
                    uid_min = int(fields[1])
                elif fields[0] == "UID_MAX":
                    uid_max = int(fields[1])
    except (OSError, ValueError) as e:
        logger.warning(f"Could not read normal user UID range from '{path}': {e}")

    return uid_min, uid_max


def get_normal_users(login_defs_path: str = LOGIN_DEFS_PATH) -> list[str]:
    uid_min, uid_max = get_uid_bounds(login_defs_path)
    users = []

    for user in pwd.getpwall():
        shell = user.pw_shell.rstrip("/").lower()
        if not uid_min <= user.pw_uid <= uid_max:
            continue
        if shell.endswith("nologin") or shell.endswith("false"):
            continue
        users.append((user.pw_uid, user.pw_name))

    return [name for _, name in sorted(users)]


def read_autologin(path: str = PLASMALOGIN_PATH) -> tuple[bool, str | None]:
    try:
        with open(path, "r") as f:
            config = f.read()
    except FileNotFoundError:
        return False, None
    except OSError as e:
        logger.warning(f"Could not read PlasmaLogin config '{path}': {e}")
        return False, None

    enabled = (
        re.search(r"^Session=gamemode\.desktop$", config, re.MULTILINE) is not None
    )
    user_match = re.search(r"^User=([^\r\n]+)$", config, re.MULTILINE)
    return enabled, user_match.group(1) if user_match else None


def _is_section(line: str) -> bool:
    return re.fullmatch(r"\[[^\r\n]+\](?:\r?\n)?", line) is not None


def _is_autologin_header(line: str) -> bool:
    return line.rstrip("\r\n") == AUTOLOGIN_HEADER


def _is_commented_autologin_header(line: str) -> bool:
    return re.fullmatch(r"# ?\[Autologin\](?:\r?\n)?", line) is not None


def _find_stanzas(lines: list[str]) -> list[tuple[int, int, bool]]:
    stanzas = []
    for i, line in enumerate(lines):
        active = _is_autologin_header(line)
        commented = _is_commented_autologin_header(line)
        if not active and not commented:
            continue

        end = i + 1
        while end < len(lines) and not _is_section(lines[end]):
            end += 1
        stanzas.append((i, end, active))

    return stanzas


def _active_stanza(user: str) -> list[str]:
    return [
        f"{AUTOLOGIN_HEADER}\n",
        f"{AUTOLOGIN_SESSION}\n",
        f"User={user}\n",
    ]


def enable_autologin(config: str, user: str) -> str:
    lines = config.splitlines(keepends=True)
    stanzas = _find_stanzas(lines)
    replacement = _active_stanza(user)

    if not stanzas:
        if config and not config.endswith(("\n", "\r")):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        return "".join([*lines, *replacement])

    out = []
    cursor = 0
    for index, (start, end, _) in enumerate(stanzas):
        if start < cursor:
            continue
        out.extend(lines[cursor:start])
        if index == 0:
            out.extend(replacement)
        cursor = end
    out.extend(lines[cursor:])
    return "".join(out)


def disable_autologin(config: str) -> str:
    lines = config.splitlines(keepends=True)
    stanzas = _find_stanzas(lines)

    for start, end, active in reversed(stanzas):
        if not active:
            continue
        lines[start + 1 : end] = [f"# {line}" for line in lines[start + 1 : end]]

    return "".join(lines)


def write_config(path: str, config: str) -> None:
    directory = os.path.dirname(path) or "."
    previous = None
    try:
        previous = os.stat(path)
    except FileNotFoundError:
        pass

    fd, tmp_path = tempfile.mkstemp(prefix=".plasmalogin.", dir=directory, text=True)
    try:
        if previous:
            os.fchmod(fd, stat.S_IMODE(previous.st_mode))
            if os.geteuid() == 0:
                os.fchown(fd, previous.st_uid, previous.st_gid)

        with os.fdopen(fd, "w") as f:
            f.write(config)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def update_autologin(enabled: bool, user: str, path: str = PLASMALOGIN_PATH) -> None:
    try:
        with open(path, "r") as f:
            current = f.read()
    except FileNotFoundError:
        current = ""

    updated = enable_autologin(current, user) if enabled else disable_autologin(current)
    if updated != current:
        write_config(path, updated)
