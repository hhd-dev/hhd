from threading import Condition, Thread, Event
import time

CACHE_TIMEOUT = 10
UPDATE_FREQ = 25
UPDATE_T = 1 / UPDATE_FREQ


class ControllerCache:
    def __init__(self) -> None:
        self._t = None
        self._cond = Condition()
        self._cached = None
        self._should_exit = Event()

    def _close_cached(self):
        with self._cond:
            start = time.perf_counter()
            while (
                time.perf_counter() - start < CACHE_TIMEOUT
                and not self._should_exit.is_set()
            ):
                self._cond.wait(UPDATE_T)
                if self._cached:
                    # Send fake events to keep everyone happy
                    # Both steam and kernel
                    self._cached.produce([self._cached.fd])
                    ctime = time.perf_counter_ns()
                    self._cached.consume(
                        [
                            {"type": "axis", "code": "left_imu_ts", "value": ctime},
                            {"type": "axis", "code": "right_imu_ts", "value": ctime},
                            {"type": "axis", "code": "imu_ts", "value": ctime},
                        ]
                    )
                else:
                    # Exit if cached became null during sleep
                    break
            if self._cached:
                self._cached.close(True)
                self._cached = None

    def add(self, c):
        tmp = None
        with self._cond:
            if self._t:
                self._should_exit.set()
                self._cond.notify_all()
                tmp = self._t
                self._t = None
        if tmp:
            tmp.join()

        with self._cond:
            self._cached = c
            self._should_exit.clear()
            self._t = Thread(target=self._close_cached)
            self._t.start()

    def get(self):
        with self._cond:
            tmp = self._cached
            self._cached = None
            self._should_exit.set()
            self._cond.notify_all()
            tmp2 = self._t
            self._t = None
        if tmp2:
            tmp2.join()
        return tmp

    def close(self):
        with self._cond:
            if self._cached:
                self._cached.close(True)
                self._cached = None
            self._should_exit.set()
            self._cond.notify_all()
