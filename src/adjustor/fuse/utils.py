import logging
import os
import sys
import time
from threading import Event, Thread

logger = logging.getLogger(__name__)

TDP_MOUNT = "/run/hhd-tdp/hwmon"
FUSE_MOUNT_SOCKET = "/run/hhd-tdp/socket"


def find_igpu():
    for hw in os.listdir("/sys/class/hwmon"):
        if not hw.startswith("hwmon"):
            continue
        if not os.path.exists(f"/sys/class/hwmon/{hw}/name"):
            continue
        with open(f"/sys/class/hwmon/{hw}/name", 'r') as f:
            if "amdgpu" not in f.read():
                continue

        if not os.path.exists(f"/sys/class/hwmon/{hw}/device"):
            logger.error(f'No device symlink found for "{hw}"')
            continue

        if not os.path.exists(f"/sys/class/hwmon/{hw}/device/local_cpulist"):
            logger.warning(
                f'No local_cpulist found for "{hw}". Assuming it is a dedicated unit.'
            )
            continue

        pth = os.path.realpath(os.path.join("/sys/class/hwmon", hw))
        return pth

    logger.error("No iGPU found. Binding TDP attributes will not be possible.")
    return None


def prepare_tdp_mount(debug: bool = False, passhtrough: bool = False):
    try:
        gpu = find_igpu()
        logger.info(f"Found GPU at:\n'{gpu}'")
        if not gpu:
            return False

        if os.path.ismount(gpu):
            logger.warning(f"GPU FUSE mount is already mounted at:\n'{gpu}'")
            return True

        if not os.path.exists(TDP_MOUNT):
            os.makedirs(TDP_MOUNT)

        if not os.path.ismount(TDP_MOUNT):
            logger.info(f"Creating bind mount for:\n'{gpu}'\nto:\n'{TDP_MOUNT}'")
            cmd = f"mount --bind '{gpu}' '{TDP_MOUNT}'"
            r = os.system(cmd)
            assert not r, f"Failed:\n{cmd}"
            logger.info(f"Making bind mount private.")
            cmd = f"mount --make-private '{TDP_MOUNT}'"
            r = os.system(cmd)
            assert not r, f"Failed:\n{cmd}"
        else:
            logger.info(f"Bind mount already exists at:\n'{TDP_MOUNT}'")

        logger.info(f"Launching FUSE mount over:\n'{gpu}'")
        # Remove socket file to avoid linux weirdness
        if os.path.exists(FUSE_MOUNT_SOCKET):
            os.remove(FUSE_MOUNT_SOCKET)
        exe_python = sys.executable
        cmd = (
            f"{exe_python} -m adjustor.fuse.driver '{gpu}'"
            + f" -o root={TDP_MOUNT} -o nonempty -o allow_other"
        )
        if passhtrough:
            cmd += " -o passthrough"
        if debug:
            cmd += " -f"
        r = os.system(cmd)
        assert not r, f"Failed:\n{cmd}"
    except Exception as e:
        logger.error(f"Error preparing fuse mount:\n{e}")
        return False

    return True


def _tdp_client(should_exit: Event, set_tdp, min_tdp, default_tdp, max_tdp):
    import socket

    CLIENT_TIMEOUT_WAIT = 0.3
    CLIENT_MAX_CMD_T = 0.05

    # Sleep until the socket is created
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        while not should_exit.is_set():
            try:
                sock.settimeout(0.5)
                sock.connect(FUSE_MOUNT_SOCKET)
                break
            except Exception as e:
                time.sleep(CLIENT_TIMEOUT_WAIT)

        logger.info(f"Connected to TDP socket.")

        def send_cmd(cmd: bytes):
            sock.send(cmd + bytes(1024 - len(cmd)))

        tdp = default_tdp

        while not should_exit.is_set():
            try:
                sock.settimeout(0.5)
                data = sock.recv(1024)
            except socket.timeout:
                time.sleep(CLIENT_TIMEOUT_WAIT)
                continue

            # FIXME: Steam uses the default value on boot
            # Use 0 for now to make sure it does not override user settings.
            default_tdp = 0
            if not data or not data.startswith(b"cmd:"):
                continue
            if b"set" in data and b"power1_cap" in data:
                try:
                    tdp = int(int(data.split(b"\0")[0].split(b":")[-1]) / 1_000_000)
                    if tdp:
                        logger.info(f"Received TDP value {tdp} from /sys.")
                        set_tdp(tdp)
                    else:
                        logger.info(
                            "Received TDP value 0 from /sys. Assuming its the default value and ignoring."
                        )
                        # Send none to remove steam notice
                        set_tdp(None)
                except:
                    logger.error(f"Failed process TDP value, received:\n{data}")
                send_cmd(b"ack\n")

            if b"get" in data:
                if b"min" in data:
                    send_cmd(b"ack:" + str(min_tdp).encode() + b"000000\n")
                elif b"max" in data:
                    send_cmd(b"ack:" + str(max_tdp).encode() + b"000000\n")
                elif b"default" in data:
                    send_cmd(b"ack:" + str(default_tdp).encode() + b"000000\n")
                else:
                    # FIXME: Value is slightly stale
                    send_cmd(b"ack:" + str(tdp).encode() + b"000000\n")
            else:
                send_cmd(b"ack\n")
            time.sleep(CLIENT_MAX_CMD_T)
    except Exception as e:
        logger.error(f"Error while communicating with FUSE server. Exiting.\n{e}")
    finally:
        if sock:
            sock.close()


def start_tdp_client(
    should_exit: Event, emit, min_tdp: int, default_tdp: int, max_tdp: int
):
    set_tdp = lambda tdp: emit and emit({"type": "tdp", "tdp": tdp})

    logger.info(f"Starting TDP client on socket:\n'{FUSE_MOUNT_SOCKET}'")
    t = Thread(
        target=_tdp_client, args=(should_exit, set_tdp, min_tdp, default_tdp, max_tdp)
    )
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prepare_tdp_mount(True)
