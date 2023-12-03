from time import sleep
from typing import Any, Generator, Literal, NamedTuple, Sequence

from anyio import open_process
from ..base import ThreadedLoop, VirtualController, Button, Axis
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


class DeviceInfo(NamedTuple):
    dev: str
    axis: Sequence[ScanElement]


ACCEL_MAPPINGS = [
    (Axis.ACCEL_X, "accel_x", "accel"),
    (Axis.ACCEL_Y, "accel_y", "accel"),
    (Axis.ACCEL_Z, "accel_z", "accel"),
]
GYRO_MAPPINGS = [
    (Axis.GYRO_X, "anglvel_x", "anglvel"),
    (Axis.GYRO_Y, "anglvel_y", "anglvel"),
    (Axis.GYRO_Z, "anglvel_z", "anglvel"),
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
        signed = "e:u" in se

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


def scan_device(dev: DeviceInfo) -> Generator[tuple[Axis | None, float], None, None]:
    with open(dev.dev, "rb") as f:
        while True:
            for se in dev.axis:
                d = f.read(se.storage_bits >> 3)
                d = int.from_bytes(d, byteorder=se.endianness)
                d = d >> se.shift
                d &= (1 << se.bits) - 1
                d = d * se.scale + se.offset
                yield se.axis, d
            yield None, 0


class AccelImu(ThreadedLoop[VirtualController]):
    def run(self):
        sens_dir = find_sensor("accel_3d")
        if not sens_dir:
            return

        dev = prepare_dev(sens_dir, ACCEL_MAPPINGS)
        if not dev:
            return

        for ax, d in scan_device(dev):
            if self.should_exit:
                return
            if ax is not None:
                self.callback.set_axis(ax, d)
            else:
                self.callback.commit()


class GyroImu(ThreadedLoop[VirtualController]):
    def run(self):
        sens_dir = find_sensor("gyro_3d")
        if not sens_dir:
            return

        dev = prepare_dev(sens_dir, GYRO_MAPPINGS)
        if not dev:
            return

        for ax, d in scan_device(dev):
            if self.should_exit:
                return
            if ax is not None:
                self.callback.set_axis(ax, d)
            else:
                self.callback.commit()
