from threading import Condition, Thread, RLock

CACHE_TIMEOUT = 5


class ControllerCache:
    def __init__(self) -> None:
        self._t = None
        self._cond = Condition()
        self._cached = None

    def _close_cached(self):
        with self._cond:
            self._cond.wait(CACHE_TIMEOUT)
            if self._cached:
                self._cached.close()
                self._cached = None

    def add(self, c):
        tmp = None
        with self._cond:
            if self._t:
                self._cond.notify_all()
                tmp = self._t
                self._t = None
        if tmp:
            tmp.join()

        with self._cond:
            self._cached = c
            self._t = Thread(target=self._close_cached)
            self._t.start()

    def get(self):
        with self._cond:
            tmp = self._cached
            self._cached = None
            self._cond.notify_all()
            tmp2 = self._t
            self._t = None
        if tmp2:
            tmp2.join()
        return tmp

    def close(self):
        with self._cond:
            self._cached = None
            self._cond.notify_all()
