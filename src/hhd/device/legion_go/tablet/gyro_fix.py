from threading import Thread, Event
import time
from hhd.controller.physical.imu import ForcedSampler

import logging

logger = logging.getLogger(__name__)


def gyro_fix(ev: Event, rate: int = 65):
    g = None
    try:
        g = ForcedSampler(["gyro_3d"], True)
        g.open()
        while not ev.is_set():
            g.sample()
            time.sleep(1 / rate)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        logger.warning(f"Gyro fix failed with error:\n{e}")
    finally:
        if g:
            g.close()


class GyroFixer:
    def __init__(self, rate: int = 65) -> None:
        self.rate = rate
        self.ev = None
        self.thread = None

    def open(self):
        logger.info("Starting gyro fixer thread.")
        self.close()
        self.ev = Event()
        self.thread = Thread(target=gyro_fix, args=(self.ev, self.rate))
        self.thread.start()

    def close(self):
        if self.ev:
            logger.info("Stopping the gyro fixer thread.")
            self.ev.set()
        if self.thread:
            self.thread.join()
        self.ev = None
        self.thread = None
