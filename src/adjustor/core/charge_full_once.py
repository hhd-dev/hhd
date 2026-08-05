import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)


def detect_ac_online() -> bool | None:
    base = "/sys/class/power_supply"
    try:
        for name in os.listdir(base):
            type_path = os.path.join(base, name, "type")
            online_path = os.path.join(base, name, "online")
            try:
                with open(type_path) as f:
                    if f.read().strip() != "Mains":
                        continue
                with open(online_path) as f:
                    return f.read().strip() == "1"
            except OSError:
                continue
    except Exception as e:
        logger.error(f"charge_once: AC detection failed: {e}")
    return None


class ChargeFullOncePolicy:
    def __init__(self) -> None:
        self.override_active: bool = False
        self.ac_online: bool | None = None
        self._last_applied: bool | None = None

    def open(self) -> None:
        self.override_active = False
        self.ac_online = None
        self._last_applied = None

    def sync(self, enabled: bool) -> None:
        self._last_applied = enabled

    def _apply(self, enabled: bool, set_fn: Callable[[bool], None]) -> None:
        if self._last_applied != enabled:
            set_fn(enabled)
            self._last_applied = enabled

    def update(
        self,
        normal_limit_enabled: bool,
        action_pressed: bool,
        set_fn: Callable[[bool], None],
    ) -> None:
        self.ac_online = detect_ac_online()

        if not normal_limit_enabled:
            if self.override_active:
                logger.info(
                    "charge_once: Canceling override, charge limit disabled by user."
                )
            self.override_active = False
            self._apply(False, set_fn)
            return

        if self.ac_online is not True:
            if self.override_active:
                logger.info(
                    "charge_once: AC disconnected or unknown, restoring charge limit."
                )
                self._apply(True, set_fn)
                self.override_active = False
            else:
                self._apply(True, set_fn)
            return

        if action_pressed:
            if self.override_active:
                logger.info(
                    "charge_once: User canceled full charge, restoring charge limit."
                )
                self._apply(True, set_fn)
                self.override_active = False
            else:
                logger.info(
                    "charge_once: Starting full-charge override, disabling charge limit."
                )
                self._apply(False, set_fn)
                self.override_active = True
            return

        if not self.override_active:
            self._apply(True, set_fn)
