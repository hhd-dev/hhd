import logging
import os
import select
from threading import Event as TEvent, Thread
from typing import Any, Generator, Literal, NamedTuple, Sequence

from hhd.controller import Axis, Event, Producer

logger = logging.getLogger(__name__)


class ScanElement(NamedTuple):
    # Output Info
    axis: Axis | None
    # Buffer Info
    endianness: Literal["little", "big"]
    signed: bool
    bits: int
    storage_bits: int
    shift: int
    # Postprocess info
    scale: float
    offset: float
    max_val: float | None


class DeviceInfo(NamedTuple):
    dev: str
    axis: Sequence[ScanElement]
    sysfs: str


ACCEL_NAMES = ["accel_3d"]
GYRO_NAMES = ["gyro_3d"]
IMU_NAMES = ["bmi323-imu", "BMI0160", "BMI0260", "i2c-10EC5280:00"]
SYSFS_TRIG_CONFIG_DIR = os.environ.get("HHD_MOUNT_TRIG_SYSFS", "/var/trig_sysfs_config")

ACCEL_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", 1, None),
    "accel_y": ("accel_x", "accel", 1, None),
    "accel_z": ("accel_y", "accel", 1, None),
    "timestamp": ("accel_ts", None, 1, None),
}
GYRO_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "anglvel_x": ("gyro_z", "anglvel", 1, None),
    "anglvel_y": ("gyro_x", "anglvel", 1, None),
    "anglvel_z": ("gyro_y", "anglvel", 1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

BMI_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", -1, None),
    "accel_y": ("accel_x", "accel", 1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_z", "anglvel", -1, None),
    "anglvel_y": ("gyro_x", "anglvel", 1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}


def find_sensor(sensors: Sequence[str]):
    IIO_BASE_DIR = "/sys/bus/iio/devices/"

    for d in os.listdir(IIO_BASE_DIR):
        if not "device" in d:
            continue

        sensor_dir = os.path.join(IIO_BASE_DIR, d)
        name_fn = os.path.join(IIO_BASE_DIR, d, "name")

        if not os.path.isfile(name_fn):
            continue

        with open(name_fn, "r") as f:
            name = f.read().strip()

        if any(sensor in name for sensor in sensors):
            logger.info(f"Found device '{name}' at\n{sensor_dir}")
            return sensor_dir, name

    return None, None


def write_sysfs(dir: str, fn: str, val: Any):
    with open(os.path.join(dir, fn), "w") as f:
        f.write(str(val))


def read_sysfs(dir: str, fn: str, default: str | None = None):
    try:
        with open(os.path.join(dir, fn), "r") as f:
            return f.read().strip()
    except Exception as e:
        if default is not None:
            return default
        raise e


def prepare_dev(
    sensor_dir: str,
    type: str,
    attr: Sequence[str],
    freq: Sequence[int] | None,
    scales: Sequence[str | None] | None,
    mappings: dict[str, tuple[Axis, str | None, float, float | None]],
    update_trigger: bool,
) -> DeviceInfo | None:
    # Prepare device buffer
    dev = os.path.join("/dev", os.path.basename(sensor_dir))
    axis = {}
    write_sysfs(sensor_dir, "buffer/enable", 0)

    # Set sampling frequency
    if freq is not None:
        for a, f in zip(attr, freq):
            sfn = os.path.join(sensor_dir, f"in_{a}_sampling_frequency")
            if os.path.isfile(sfn):
                write_sysfs(sensor_dir, f"in_{a}_sampling_frequency", f)

    # Set scale
    if scales is not None:
        for a, s in zip(attr, scales):
            if not s:
                continue
            sfn = os.path.join(sensor_dir, f"in_{a}_scale")
            if os.path.isfile(sfn):
                write_sysfs(sensor_dir, f"in_{a}_scale", s)

    # Set trigger
    if update_trigger:
        trig = None
        for s in os.listdir("/sys/bus/iio/devices/"):
            if s.startswith("trigger"):
                name = read_sysfs(os.path.join("/sys/bus/iio/devices/", s), "name")
                pref = f"{type}-dev"
                if name.startswith(pref):
                    idx = name[len(pref) :]
                    if sensor_dir.endswith(idx):
                        trig = name
                        break
        if trig:
            write_sysfs(sensor_dir, "trigger/current_trigger", trig)

    # Disable all scan elements
    for s in os.listdir(os.path.join(sensor_dir, "scan_elements")):
        if s.endswith("_en"):
            write_sysfs(sensor_dir, os.path.join("scan_elements", s), 0)

    # Selectively enable required ones and fill up buffer
    for fn in os.listdir(os.path.join(sensor_dir, "scan_elements")):
        if not fn.startswith("in_") or not fn.endswith("_en"):
            continue
        fn = fn[3:-3]

        # Prepare buffer metadata
        idx = int(read_sysfs(sensor_dir, f"scan_elements/in_{fn}_index"))
        if idx == -1:
            logger.error(
                f"Device '{dev}' element '{fn}' does not support buffered capture."
            )
            return None
        se = read_sysfs(sensor_dir, f"scan_elements/in_{fn}_type")
        endianness = "big" if se.startswith("be:") else "little"
        signed = "e:s" in se

        bits = int(se[se.index(":") + 2 : se.index(":") + 4])
        storage_bits = int(se[se.index("/") + 1 : se.index("/") + 3])
        shift = int(se[-1])

        # Prepare scan metadata
        if fn in mappings:
            ax, atr, scale_usr, max_val = mappings[fn]
            if atr:
                offset = float(read_sysfs(sensor_dir, f"in_{atr}_offset", "0"))
                scale = float(read_sysfs(sensor_dir, f"in_{atr}_scale"))
            else:
                offset = 0
                scale = 1
            scale *= scale_usr
            write_sysfs(sensor_dir, f"scan_elements/in_{fn}_en", 1)
        else:
            ax = max_val = None
            offset = 0
            scale = 1

        axis[idx] = ScanElement(
            ax,
            endianness,
            signed,
            bits,
            storage_bits,
            shift,
            scale,
            offset,
            max_val,
        )
    write_sysfs(sensor_dir, "buffer/enable", 1)

    axis_arr = tuple(axis[i] for i in sorted(axis))
    return DeviceInfo(dev, axis_arr, sensor_dir)


def close_dev(dev: DeviceInfo):
    write_sysfs(dev.sysfs, "buffer/enable", 0)


def get_size(dev: DeviceInfo):
    out = 0
    for s in dev.axis:
        if out % s.storage_bits:
            # Align bytes
            out = (out // s.storage_bits + 1) * s.storage_bits
        out += s.storage_bits
    return out >> 3


class IioReader(Producer):
    def __init__(
        self,
        types: Sequence[str],
        attr: Sequence[str],
        freq: Sequence[int] | None,
        scale: Sequence[str | None] | None,
        mappings: dict[str, tuple[Axis, str | None, float, float | None]],
        update_trigger: bool = False,
        legion_fix: bool = False,
    ) -> None:
        self.types = types
        self.attr = attr
        self.freq = freq
        self.scale = scale
        self.mappings = mappings
        self.update_trigger = update_trigger
        self.fd = 0
        self.dev = None
        self.legion_fix = legion_fix

    def open(self):
        sens_dir, type = find_sensor(self.types)
        if not sens_dir or not type:
            return []

        dev = prepare_dev(
            sens_dir,
            type,
            self.attr,
            self.freq,
            self.scale,
            self.mappings,
            self.update_trigger,
        )

        if not dev:
            logger.error(
                "IMU not found for this device, gyro will not work.\n"
                + "You need to install the IMU driver for your device, see the readme."
            )
            return []

        self.buf = None
        self.prev = {}
        self.dev = dev
        self.fd = os.open(dev.dev, os.O_RDONLY)
        self.size = get_size(dev)

        return [self.fd]

    def close(self, exit: bool):
        if self.dev:
            close_dev(self.dev)
            self.dev = None
        if self.fd:
            os.close(self.fd)
            self.fd = 0
        return True

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        if self.fd not in fds or not self.dev:
            return []

        data = os.read(self.fd, self.size)
        if self.buf == data:
            return []
        self.buf = data

        # Empty the buffer preventing repeated calls
        while select.select([self.fd], [], [], 0)[0]:
            data = os.read(self.fd, self.size)

        out: list[Event] = []
        ofs = 0
        for se in self.dev.axis:
            # Align bytes
            if ofs % se.storage_bits:
                ofs = (ofs // se.storage_bits + 1) * se.storage_bits

            # Grab value if required
            if se.axis:
                # TODO: Implement parsing iio fully, by adding shifting and cutoff
                d = data[ofs >> 3 : (ofs >> 3) + (se.storage_bits >> 3)]
                d_raw = int.from_bytes(d, byteorder=se.endianness, signed=se.signed)
                # d = d >> se.shift
                # d &= (1 << se.bits) - 1
                d = d_raw * se.scale + se.offset

                if se.max_val is not None:
                    if d > 0:
                        d = min(d, se.max_val)
                    else:
                        d = max(d, -se.max_val)

                if se.axis not in self.prev or self.prev[se.axis] != d:
                    if not (
                        self.legion_fix and (d_raw == -124 or d_raw // 1000 == -125)
                    ):
                        # Legion go likes to overflow to -124 in both directions
                        # skip this number to avoid jitters
                        # With a kernel patch to allow higher resolution, this happens
                        # with the following numbers
                        # 4d 95 f3 c7: -124715
                        # 33 97 f3 c7: -124718
                        # Reported by hhd: -124422, -124419
                        # Legion go axis tester
                        # import time
                        # if se.axis == "gyro_x":
                        #     print(f"{time.time() % 1:.3f} {d_raw}")
                        out.append(
                            {
                                "type": "axis",
                                "code": se.axis,
                                "value": d,
                            }
                        )
                    self.prev[se.axis] = d
            ofs += se.storage_bits

        # TODO: Clean this up
        # Hide duplicate events
        # if (len(out) == 1 and out[0]['code'].endswith('_ts')):
        #     return []
        return out


class AccelImu(IioReader):
    def __init__(self, freq=None, scale=None) -> None:
        super().__init__(
            ACCEL_NAMES, ["accel"], [freq] if freq else None, [scale], ACCEL_MAPPINGS
        )


class GyroImu(IioReader):
    def __init__(
        self, freq=None, scale=None, map=None, legion_fix: bool = False
    ) -> None:
        super().__init__(
            GYRO_NAMES,
            ["anglvel"],
            [freq] if freq else None,
            [scale],
            map if map else GYRO_MAPPINGS,
            legion_fix=legion_fix,
        )


class CombinedImu(IioReader):
    def __init__(
        self,
        freq: int = 400,
        map: dict[str, tuple[Axis, str | None, float, float | None]] | None = None,
        gyro_scale: str | None = None,
        accel_scale: str | None = None,
    ) -> None:
        super().__init__(
            IMU_NAMES,
            ["anglvel", "accel"],
            [freq, freq] if freq else None,
            [gyro_scale, accel_scale],
            map if map is not None else BMI_MAPPINGS,
        )


class ForcedSampler:
    def __init__(self, devices: Sequence[str], keep_fds: bool = False) -> None:
        self.devices = devices
        self.fds = []
        self.keep_fds = keep_fds

    def open(self):
        self.fds = []
        self.paths = []
        for d in self.devices:
            f, _ = find_sensor([d])
            if not f:
                continue
            if "accel" in d:
                p = os.path.join(f, "in_accel_x_raw")
            elif "gyro" in d:
                p = os.path.join(f, "in_anglvel_x_raw")
            else:
                continue

            self.paths.append(p)
            if self.keep_fds:
                self.fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))

    def sample(self):
        if self.keep_fds:
            for fd in select.select(self.fds, [], [], 0)[0]:
                os.read(fd, 20)
            for fd in select.select(self.fds, [], [], 0)[0]:
                os.lseek(fd, 0, os.SEEK_SET)
        else:
            for p in self.paths:
                with open(p, "rb") as f:
                    f.read()

    def close(self):
        for fd in self.fds:
            os.close(fd)


class HrtimerTrigger(IioReader):
    ACCEL_NAMES = ACCEL_NAMES
    GYRO_NAMES = GYRO_NAMES
    IMU_NAMES = IMU_NAMES

    def __init__(
        self,
        freq: int,
        devices: Sequence[Sequence[str]] = [IMU_NAMES, GYRO_NAMES, ACCEL_NAMES],
    ) -> None:
        self.freq = freq
        self.devices = devices
        self.old_triggers = {}
        self.opened = False

    def open(self):
        import subprocess

        # Initialize modules
        try:
            subprocess.run(["modprobe", "industrialio-sw-trigger"], capture_output=True)
            subprocess.run(["modprobe", "iio-trig-sysfs"], capture_output=True)
            subprocess.run(["modprobe", "iio-trig-hrtimer"], capture_output=True)
            os.makedirs(SYSFS_TRIG_CONFIG_DIR, exist_ok=True)
            subprocess.run(
                ["mount", "-t", "configfs", "none", SYSFS_TRIG_CONFIG_DIR],
                capture_output=True,
            )
        except Exception as e:
            logger.warning(
                f"Could not initialize software hrtimer. It may be initialized. Error:\n{e}"
            )

        # Create trigger
        try:
            trig_dir = os.path.join(SYSFS_TRIG_CONFIG_DIR, "iio/triggers/hrtimer/hhd")
            if not os.path.isdir(trig_dir):
                os.makedirs(trig_dir, exist_ok=True)
        except Exception as e:
            logger.error(
                f"Could not create 'hhd' trigger. IMU will not work. Error:\n{e}"
            )
            return False
        self.opened = True

        # Find trigger
        trig = None
        for fn in os.listdir("/sys/bus/iio/devices"):
            if not fn.startswith("trigger"):
                continue
            with open(os.path.join("/sys/bus/iio/devices", fn, "name"), "r") as f:
                if f.read().strip() == "hhd":
                    trig = fn
                    break
        if not trig:
            logger.warning("Imu timer trigger not found, IMU will not work.")
            return False

        # Set frequency
        try:
            with open(
                os.path.join("/sys/bus/iio/devices", trig, "sampling_frequency"), "w"
            ) as f:
                f.write(str(self.freq))
        except Exception as e:
            logger.warning("Could not set sampling frequency, IMU will not work.")
            return False

        self.old_triggers = {}
        found = False
        for d in self.devices:
            s, _ = find_sensor(d)
            if not s:
                continue

            buff_fn = os.path.join(s, "buffer/enable")
            trig_fn = os.path.join(s, "trigger/current_trigger")
            with open(buff_fn, "w") as f:
                f.write("0")
            with open(trig_fn, "r") as f:
                self.old_triggers[trig_fn] = (f.read(), buff_fn)
            with open(trig_fn, "w") as f:
                f.write(f"hhd")
            found = True

        if not found:
            self.close()
            logger.error(
                "IMU not found for this device, gyro will not work.\n"
                + "You need to install the IMU driver for your device, see the readme."
            )
            return False

        return True

    def close(self):
        if not self.opened:
            return
        self.opened = False

        for trig, (name, buff) in self.old_triggers.items():
            try:
                with open(buff, "w") as f:
                    f.write("0")
                with open(trig, "w") as f:
                    f.write(name)
            except Exception:
                logger.error(f"Could not restore original trigger:\n{trig} to {name}")

        try:
            trig_dir = os.path.join(SYSFS_TRIG_CONFIG_DIR, "iio/triggers/hrtimer/hhd")
            os.rmdir(trig_dir)
        except Exception as e:
            logger.error(f"Could not delete hrtimer trigger. Error:\n{e}")


def _sysfs_trig_sampler(ev: TEvent, trigger: int, rate: int = 65):
    import time

    trig = None
    for fn in os.listdir("/sys/bus/iio/devices/"):
        if not fn.startswith("trigger"):
            continue
        tmp = os.path.join("/sys/bus/iio/devices/", fn)
        with open(os.path.join(tmp, "name")) as f:
            name = f.read().strip()

        if name == f"sysfstrig{trigger}":
            trig = os.path.join(tmp, "trigger_now")
            break

    if trig is None:
        logger.warning(f"Trigger `sysfstrig{trigger}` not found.")
        return

    fd = -1
    delay = 1 / rate
    try:
        fd = os.open(trig, os.O_WRONLY)
        while not ev.is_set():
            os.write(fd, b"1")
            os.lseek(fd, 0, os.SEEK_SET)
            time.sleep(delay)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        logger.warning(f"Trig sampler failed with error:\n{e}")
    finally:
        if fd != -1:
            os.close(fd)


class SoftwareTrigger(IioReader):
    ACCEL_NAMES = ACCEL_NAMES
    GYRO_NAMES = GYRO_NAMES
    IMU_NAMES = IMU_NAMES

    BEGIN_ID: int = 5335
    ATTEMPTS: int = 900

    def __init__(
        self,
        freq: int,
        devices: Sequence[Sequence[str]] = [IMU_NAMES, GYRO_NAMES, ACCEL_NAMES],
    ) -> None:
        self.devices = devices
        self.old_triggers = {}
        self.freq = freq
        self.opened = False
        self.ev = None
        self.thread = None

    def open(self):
        import time

        try:
            os.system("modprobe iio-trig-sysfs")
        except Exception:
            logger.warning(f"Could not modprobe software triggers")

        for id in range(
            SoftwareTrigger.BEGIN_ID,
            SoftwareTrigger.BEGIN_ID + SoftwareTrigger.ATTEMPTS,
        ):
            # Try to remove stale trigger
            try:
                with open(
                    "/sys/bus/iio/devices/iio_sysfs_trigger/remove_trigger", "w"
                ) as f:
                    f.write(str(id))
            except Exception:
                pass
            # Add new trigger
            try:
                with open(
                    "/sys/bus/iio/devices/iio_sysfs_trigger/add_trigger", "w"
                ) as f:
                    f.write(str(id))
                break
            except Exception:
                pass
            time.sleep(0.02)
        else:
            logger.error(f"Failed to create software trigger.")
            return False
        self.id = id

        self.old_triggers = {}
        for d in self.devices:
            s, _ = find_sensor(d)
            if not s:
                continue

            buff_fn = os.path.join(s, "buffer/enable")
            trig_fn = os.path.join(s, "trigger/current_trigger")
            with open(buff_fn, "w") as f:
                f.write("0")
            with open(trig_fn, "r") as f:
                self.old_triggers[trig_fn] = (f.read(), buff_fn)
            with open(trig_fn, "w") as f:
                f.write(f"sysfstrig{self.id}")

        self.ev = TEvent()
        self.thread = Thread(target=_sysfs_trig_sampler, args=(self.ev, id, self.freq))
        self.thread.start()
        self.opened = True

        return True

    def close(self):
        if not self.opened:
            return

        # Stop trigger
        self.opened = False
        if self.ev:
            self.ev.set()
        if self.thread:
            self.thread.join()
        self.ev = None
        self.thread = None

        # Remove from current sensors
        for trig, (name, buff) in self.old_triggers.items():
            try:
                with open(buff, "w") as f:
                    f.write("0")
                with open(trig, "w") as f:
                    f.write(name)
            except Exception:
                logger.error(f"Could not restore original trigger:\n{trig} to {name}")

        # Delete trigger
        try:
            logger.info(f"Closing trigger {self.id}")
            with open(
                "/sys/bus/iio/devices/iio_sysfs_trigger/remove_trigger", "w"
            ) as f:
                f.write(str(self.id))
        except Exception:
            logger.error(f"Could not delete sysfs trigger with id {self.id}")


__all__ = ["IioReader", "AccelImu", "GyroImu", "HrtimerTrigger"]
