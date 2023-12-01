from time import sleep
from ..base import ThreadedLoop, VirtualController, Button, Axis
import os

import logging

logger = logging.getLogger(__name__)


def prepare_sensors():
    IIO_BASE_DIR = "/sys/bus/iio/devices/"
    accel = None
    gyro = None

    for d in os.listdir(IIO_BASE_DIR):
        if not "device" in d:
            continue

        sensor_dir = os.path.join(IIO_BASE_DIR, d)
        name_fn = os.path.join(IIO_BASE_DIR, d, "name")

        if not os.path.isfile(name_fn):
            continue

        with open(name_fn, "r") as f:
            name = f.read()

        match (name.strip()):
            case "accel_3d":
                accel = sensor_dir
            case "gyro_3d":
                gyro = sensor_dir

    logger.info(f"Found accelerometer at\n{accel}. Found Gyroscope at:\n{gyro}")

    for name, sensor, freq in (
        ("Accelerometer", accel, "in_accel_sampling_frequency"),
        ("Gyroscope", gyro, "in_anglvel_sampling_frequency"),
    ):
        if sensor:
            try:
                fn = os.path.join(sensor, freq)
                with open(fn, "w") as f:
                    f.write("1000\n")
                with open(fn, "r") as f:
                    val = float(f.read().strip())
                logger.info(f"Set {name} sampling rate to: {val:.3f}")
            except Exception as e:
                logger.error(f"Could not change {name} frequency, error:\n{e}")
    return accel, gyro


def read_sysfs(path: str, name: str):
    with open(os.path.join(path, name), "r") as f:
        return float(f.read().strip())


def open_sysfs(path: str, name: str):
    return open(os.path.join(path, name), "r")


class Imu(ThreadedLoop[VirtualController]):
    def run(self):
        accel, gyro = prepare_sensors()

        if not accel or not gyro:
            logger.error(
                f"Did not find either accel or gyro, gyro emulation is disabled."
            )
            return

        accel_ofs = read_sysfs(accel, "in_accel_offset")
        accel_scale = read_sysfs(accel, "in_accel_scale")
        gyro_ofs = read_sysfs(gyro, "in_anglvel_offset")
        gyro_scale = read_sysfs(gyro, "in_anglvel_scale")

        with (
            open_sysfs(gyro, "in_anglvel_x_raw") as fd_gx,
            open_sysfs(gyro, "in_anglvel_y_raw") as fd_gy,
            open_sysfs(gyro, "in_anglvel_z_raw") as fd_gz,
            open_sysfs(accel, "in_accel_x_raw") as fd_ax,
            open_sysfs(accel, "in_accel_y_raw") as fd_ay,
            open_sysfs(accel, "in_accel_z_raw") as fd_az,
        ):
            while True:
                if self.should_exit:
                    return

                try:
                    gyro_x = float(fd_gx.read()) * gyro_scale + gyro_ofs
                    fd_gx.seek(0)
                    gyro_y = float(fd_gy.read()) * gyro_scale + gyro_ofs
                    fd_gy.seek(0)
                    gyro_z = float(fd_gz.read()) * gyro_scale + gyro_ofs
                    fd_gz.seek(0)

                    accel_x = float(fd_ax.read()) * accel_scale + accel_ofs
                    fd_ax.seek(0)
                    accel_y = float(fd_ay.read()) * accel_scale + accel_ofs
                    fd_ay.seek(0)
                    accel_z = float(fd_az.read()) * accel_scale + accel_ofs
                    fd_az.seek(0)

                    self.callback.set_axis(Axis.GYRO_X, gyro_x)
                    self.callback.set_axis(Axis.GYRO_Y, gyro_y)
                    self.callback.set_axis(Axis.GYRO_Z, gyro_z)

                    self.callback.set_axis(Axis.ACCEL_X, accel_x)
                    self.callback.set_axis(Axis.ACCEL_Y, accel_y)
                    self.callback.set_axis(Axis.ACCEL_Z, accel_z)

                    self.callback.flush()
                except ValueError as e:
                    print(e)
                    sleep(0.2)
