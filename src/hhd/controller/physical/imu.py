import select
from time import sleep
from typing import Any, Generator, Literal, NamedTuple, Sequence

from anyio import open_process

from hhd.controller.base import Event
from ..base import Axis, Producer
import os

import logging

logger = logging.getLogger(__name__)


class ScanElement(NamedTuple):
    # Output Info
    axis: Axis
    # Buffer Info
    endianness: Literal["little", "big"]
    signed: bool
    bits: int
    storage_bits: int
    shift: int
    # Postprocess info
    scale: float
    offset: float


class DeviceInfo(NamedTuple):
    dev: str
    axis: Sequence[ScanElement]


ACCEL_MAPPINGS = [
    ("accel_z", "accel_x", "accel"),
    ("accel_x", "accel_y", "accel"),
    ("accel_y", "accel_z", "accel"),
]
GYRO_MAPPINGS = [
    ("gyro_z", "anglvel_x", "anglvel"),
    ("gyro_x", "anglvel_y", "anglvel"),
    ("gyro_y", "anglvel_z", "anglvel"),
]


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
    sensor_dir: str, mappings: Sequence[tuple[Axis, str, str]]
) -> DeviceInfo | None:
    # @TODO: Add boosting sampling frequency support

    # Prepare device buffer
    dev = os.path.join("/dev", os.path.basename(sensor_dir))
    axis = {}
    write_sysfs(sensor_dir, "buffer/enable", 0)

    # Disable all scan elements
    for s in os.listdir(os.path.join(sensor_dir, "scan_elements")):
        if s.endswith("_en"):
            write_sysfs(sensor_dir, os.path.join("scan_elements", s), 0)

    # Selectively enable required ones and fill up buffer
    for ax, fn, meta_fn in mappings:
        write_sysfs(sensor_dir, f"scan_elements/in_{fn}_en", 1)

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
        offset = float(read_sysfs(sensor_dir, f"in_{meta_fn}_offset"))
        scale = float(read_sysfs(sensor_dir, f"in_{meta_fn}_scale"))

        axis[idx] = ScanElement(
            ax, endianness, signed, bits, storage_bits, shift, scale, offset
        )
    write_sysfs(sensor_dir, "buffer/enable", 1)

    axis_arr = tuple(axis[i] for i in sorted(axis))
    return DeviceInfo(dev, axis_arr)


def process_scan_event(data: bytes, ofs: int, se: ScanElement):
    # TODO: Implement parsing iio fully, by adding shifting and cutoff
    d = data[ofs >> 3 : (ofs >> 3) + (se.storage_bits >> 3)]
    d = int.from_bytes(d, byteorder=se.endianness, signed=se.signed)
    # d = d >> se.shift
    # d &= (1 << se.bits) - 1
    d = d * se.scale + se.offset
    return d


def get_size(dev: DeviceInfo):
    out = 0
    for s in dev.axis:
        out += s.storage_bits
    return out >> 3


class Imu(Producer):
    def __init__(self, name: str, mappings) -> None:
        self.name = name
        self.mappings = mappings
        self.fd = 0

    def open(self):
        sens_dir = find_sensor(self.name)
        if not sens_dir:
            return []

        dev = prepare_dev(sens_dir, self.mappings)
        if not dev:
            return []

        self.dev = dev
        self.fd = os.open(dev.dev, os.O_RDONLY)
        self.size = get_size(dev)

        return [self.fd]

    def close(self, exit: bool):
        if self.fd:
            os.close(self.fd)
        self.fd = 0
        return True

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        if self.fd not in fds:
            return []

        data = os.read(self.fd, self.size)

        # Empty the buffer preventing repeated calls
        while select.select([self.fd], [], [], 0)[0]:
            data = os.read(self.fd, self.size)

        out = []
        ofs = 0
        for se in self.dev.axis:
            out.append(
                {
                    "type": "axis",
                    "axis": se.axis,
                    "val": process_scan_event(data, ofs, se),
                }
            )
            ofs += se.storage_bits
        return out


class AccelImu(Imu):
    def __init__(self) -> None:
        super().__init__("accel_3d", ACCEL_MAPPINGS)


class GyroImu(Imu):
    def __init__(self) -> None:
        super().__init__("gyro_3d", GYRO_MAPPINGS)
