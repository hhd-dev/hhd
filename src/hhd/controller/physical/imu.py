import select
from typing import Any, Generator, Literal, NamedTuple, Sequence

from hhd.controller import Axis, Event, Axis, Producer
import os

import logging

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


ACCEL_MAPPINGS: dict[str, tuple[Axis, float | None]] = {
    "accel_x": ("accel_z", 3),
    "accel_y": ("accel_x", 3),
    "accel_z": ("accel_y", 3),
    "timestamp": ("accel_ts", None),
}
GYRO_MAPPINGS: dict[str, tuple[Axis, float | None]] = {
    "anglvel_x": ("gyro_z", None),
    "anglvel_y": ("gyro_x", None),
    "anglvel_z": ("gyro_y", None),
    "timestamp": ("gyro_ts", None),
}


def find_sensor(sensor: str):
    IIO_BASE_DIR = "/sys/bus/iio/devices/"

    for d in os.listdir(IIO_BASE_DIR):
        if not "device" in d:
            continue

        sensor_dir = os.path.join(IIO_BASE_DIR, d)
        name_fn = os.path.join(IIO_BASE_DIR, d, "name")

        if not os.path.isfile(name_fn):
            continue

        with open(name_fn, "r") as f:
            name = f.read()

        if name.strip() == sensor:
            logger.info(f"Found device '{sensor}' at\n{sensor_dir}")
            return sensor_dir

    return None


def write_sysfs(dir: str, fn: str, val: Any):
    with open(os.path.join(dir, fn), "w") as f:
        f.write(str(val))


def read_sysfs(dir: str, fn: str):
    with open(os.path.join(dir, fn), "r") as f:
        return f.read().strip()


def prepare_dev(
    sensor_dir: str,
    type: str,
    attr: str,
    freq: int | None,
    mappings: dict[str, tuple[Axis, float | None]],
    update_trigger: bool,
) -> DeviceInfo | None:
    # Prepare device buffer
    dev = os.path.join("/dev", os.path.basename(sensor_dir))
    axis = {}
    write_sysfs(sensor_dir, "buffer/enable", 0)

    # Set sampling frequency
    if freq is not None:
        sfn = os.path.join(sensor_dir, f"in_{attr}_sampling_frequency")
        if os.path.isfile(sfn):
            write_sysfs(sensor_dir, f"in_{attr}_sampling_frequency", freq)

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
            ax, max_val = mappings[fn]
            write_sysfs(sensor_dir, f"scan_elements/in_{fn}_en", 1)
        else:
            ax = max_val = None

        if fn != "timestamp":
            offset = float(read_sysfs(sensor_dir, f"in_{attr}_offset"))
            scale = float(read_sysfs(sensor_dir, f"in_{attr}_scale"))
        else:
            offset = 0
            scale = 1

        axis[idx] = ScanElement(
            ax, endianness, signed, bits, storage_bits, shift, scale, offset, max_val
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
        type: str,
        attr: str,
        freq: int | None,
        mappings: dict[str, tuple[Axis, float | None]],
        update_trigger: bool = False,
    ) -> None:
        self.type = type
        self.attr = attr
        self.freq = freq
        self.mappings = mappings
        self.update_trigger = update_trigger
        self.fd = 0

    def open(self):
        sens_dir = find_sensor(self.type)
        if not sens_dir:
            return []

        dev = prepare_dev(
            sens_dir,
            self.type,
            self.attr,
            self.freq,
            self.mappings,
            self.update_trigger,
        )
        if not dev:
            return []

        self.buf = None
        self.prev = {}
        self.dev = dev
        self.fd = os.open(dev.dev, os.O_RDONLY)
        self.size = get_size(dev)

        return [self.fd]

    def close(self, exit: bool):
        if self.fd:
            os.close(self.fd)
            self.fd = 0
        if self.dev:
            close_dev(self.dev)
            self.dev = None
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
                d = int.from_bytes(d, byteorder=se.endianness, signed=se.signed)
                # d = d >> se.shift
                # d &= (1 << se.bits) - 1
                d = d * se.scale + se.offset

                if se.max_val is not None:
                    if d > 0:
                        d = min(d, se.max_val)
                    else:
                        d = max(d, -se.max_val)

                if se.axis not in self.prev or self.prev[se.axis] != d:
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
    def __init__(self, freq=None) -> None:
        super().__init__("accel_3d", "accel", freq, ACCEL_MAPPINGS)


class GyroImu(IioReader):
    def __init__(self, freq=None) -> None:
        super().__init__("gyro_3d", "anglvel", freq, GYRO_MAPPINGS)


class ForcedSampler:
    def __init__(self, devices: Sequence[str], keep_fds: bool = False) -> None:
        self.devices = devices
        self.fds = []
        self.keep_fds = keep_fds

    def open(self):
        self.fds = []
        self.paths = []
        for d in self.devices:
            f = find_sensor(d)
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


# class SoftwareTrigger(IioReader):
#     BEGIN_ID: int = 72
#     ATTEMPTS: int = 3

#     def __init__(self, devices: Sequence[str]) -> None:
#         self.devices = devices
#         self.old_triggers = {}

#     def open(self):
#         for id in range(
#             SoftwareTrigger.BEGIN_ID,
#             SoftwareTrigger.BEGIN_ID + SoftwareTrigger.ATTEMPTS,
#         ):
#             try:
#                 with open(
#                     "/sys/bus/iio/devices/iio_sysfs_trigger/add_trigger", "w"
#                 ) as f:
#                     f.write(str(id))
#                 break
#             except Exception as e:
#                 print(e)
#         else:
#             logger.error(f"Failed to create software trigger.")
#             return
#         self.id = id

#         self.old_triggers = {}
#         for d in self.devices:
#             s = find_sensor(d)
#             if not s:
#                 continue
#             with open(os.path.join(s, "buffer/enable"), "w") as f:
#                 f.write("0")
#             trig_fn = os.path.join(s, "trigger/current_trigger")
#             with open(trig_fn, "r") as f:
#                 self.old_triggers[trig_fn] = f.read()
#             with open(trig_fn, "w") as f:
#                 f.write(f"sysfstrig{self.id}")

#     def close(self):
#         for trig, name in self.old_triggers.items():
#             try:
#                 with open(trig, "w") as f:
#                     f.write(name)
#             except Exception:
#                 logger.error(f"Could not restore original trigger:\n{trig} to {name}")

#         try:
#             with open(
#                 "/sys/bus/iio/devices/iio_sysfs_trigger/remove_trigger", "w"
#             ) as f:
#                 f.write(str(self.id))
#         except Exception:
#             logger.error(f"Could not delete sysfs trigger with id {self.id}")


__all__ = ["IioReader", "AccelImu", "GyroImu"]
