import logging
from typing import Sequence
import os
import time

from hhd.plugins import Config, Context, HHDPlugin, load_relative_yaml
from .power import (
    get_windows_bootnum,
    boot_windows,
    emergency_hibernate,
    emergency_shutdown,
    delete_temporary_swap,
)

logger = logging.getLogger(__name__)

TEMP_CHECK_INTERVAL = 10
# Chill for the first 10 minutes to avoid bricking installs if a device
# has e.g., a battery bug that trips the condition incorrectly
TEMP_CHECK_INITIALIZE = 300
BATTERY_LOW_THRESHOLD = 5
LAST_ATTEMPT_WAIT = 5
LAST_ATTEMPT_BAIL = 30


def thermal_check(therm: dict[str, int], bat: str | None, last_attempt: float = 0, wakeup: bool = False):
    found = False
    for path, temp in therm.items():
        with open(path) as f:
            curr = int(f.read())
            if curr >= temp:
                logger.warning(
                    f"Thermal zone {path} reached {curr // 1000}C, hibernating."
                )
                found = True

    if bat and not found:
        with open(bat + "/status") as f:
            dc = "discharging" in bat.lower()

        with open(bat + "/capacity") as f:
            curr = int(f.read())
            if dc and curr <= BATTERY_LOW_THRESHOLD:
                logger.warning(f"Battery level reached {curr}%, hibernating.")
                found = True

    if not found:
        return False

    if not wakeup and time.time() - last_attempt < LAST_ATTEMPT_WAIT:
        # There is a small chance that systemctl returns control too early
        # and we run the event loop and fall in the if statement below.
        # Therefore, unless this was triggered by a  wakeup, we should
        # wait a bit.
        return False
    elif time.time() - last_attempt < LAST_ATTEMPT_BAIL:
        # Bail out if we woke up too soon
        # This is to avoid a loop of hibernation attempts and wakeup
        # Hibernation requires ~20s to complete, then boot another 20
        # so a user should not be able to trigger this by waking up
        emergency_shutdown()
        return True
    else:
        emergency_hibernate(shutdown=True)
        return True


def set_bat_alarm(bat: str | None):
    # If we do not do this, systemd will not and the system will wakeup
    # randomly. Systemd only uses the alarm in sleep-then-hibernate and
    # leaves it dangling otherwise.
    # Only touch it if the setting is enabled.
    if not bat or not os.path.exists(bat + "/alarm"):
        return

    if os.path.exists(bat + "/energy_full"):
        with open(bat + "/energy_full") as f:
            full = int(f.read())
    else:
        with open(bat + "/charge_full") as f:
            full = int(f.read())

    # Go a bit below the threshold to make sure we hibernate when we wake up.
    lvl = BATTERY_LOW_THRESHOLD * 85 * full // 100 // 100
    logger.warning(
        f"Setting battery alarm to {lvl}/{full} mAh/mWh ({BATTERY_LOW_THRESHOLD}%)"
    )

    with open(bat + "/alarm", "w") as f:
        f.write(str(lvl))


class PowerPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"power"
        self.priority = 50
        self.log = "powr"
        self.win_bootnum = None
        self.win_bootnum = get_windows_bootnum()
        self.therm = {}
        self.init = 0
        self.last_check = 0
        self.check_thermal = False
        self.bat = None
        self.alarm_set = False
        self.last_attempt = 0

    def open(
        self,
        emit,
        context: Context,
    ):
        self.started = False
        self.context = context
        self.emit = emit

        self.init = time.time()
        self.therm = {}
        self.bat = None

        try:
            for therm in os.listdir("/sys/class/thermal"):
                if not therm.startswith("thermal_zone"):
                    continue

                with open(f"/sys/class/thermal/{therm}/type") as f:
                    if "acpitz" not in f.read():
                        continue

                for trip in os.listdir(f"/sys/class/thermal/{therm}"):
                    if not trip.startswith("trip_point_"):
                        continue

                    if not trip.endswith("_type"):
                        continue

                    with open(f"/sys/class/thermal/{therm}/{trip}") as f:
                        if "hot" not in f.read():
                            continue

                    with open(
                        f"/sys/class/thermal/{therm}/{trip.replace("_type", "_temp")}"
                    ) as f:
                        self.therm[f"/sys/class/thermal/{therm}/temp"] = int(f.read())
                        break

            for bat in os.listdir("/sys/class/power_supply"):
                if not bat.startswith("BAT"):
                    continue

                with open(f"/sys/class/power_supply/{bat}/type") as f:
                    if "Battery" not in f.read():
                        continue

                self.bat = f"/sys/class/power_supply/{bat}"

        except Exception as e:
            logger.error(f"Failed to read thermal zones: {e}")

        if self.therm:
            logger.info(f"Found thermal zones:")
            for path, temp in self.therm.items():
                logger.info(f"  {path}: hot @ {temp // 1000}C")
        if self.bat:
            logger.info(f"Found battery:\n{self.bat}")

    def settings(self):
        set = {"gamemode": {"power": load_relative_yaml("power.yml")}}

        if self.win_bootnum is None:
            del set["gamemode"]["power"]["children"]["reboot_windows"]

        return set

    def update(self, conf: Config):
        if self.win_bootnum is not None and conf.get_action(
            "gamemode.power.reboot_windows"
        ):
            boot_windows()

        if conf.get_action("gamemode.power.hibernate"):
            status = emergency_hibernate(shutdown=False)
            conf["gamemode.power.status"] = status

        self.check_thermal = conf.get("gamemode.power.hibernate_auto", False)
        if self.check_thermal:
            if not self.alarm_set:
                self.alarm_set = True
                if self.bat:
                    try:
                        set_bat_alarm(self.bat)
                    except Exception as e:
                        logger.error(f"Failed to set battery alarms:\n{e}")

            curr = time.time()
            if (
                curr - self.last_check > TEMP_CHECK_INTERVAL
                and curr - self.init > TEMP_CHECK_INITIALIZE
            ):
                self.last_check = curr
                try:
                    if thermal_check(self.therm, self.bat, self.last_attempt):
                        self.last_attempt = time.time()
                except Exception as e:
                    logger.error(f"Failed to check thermal zones:\n{e}")
                    self.therm = {}
                    self.bat = None

    def notify(self, events: Sequence):
        for ev in events:
            if ev["type"] == "special" and ev.get("event", None) == "wakeup":
                delete_temporary_swap()

                if self.check_thermal:
                    try:
                        # Battery alarms neeed to be reset after hibernation
                        set_bat_alarm(self.bat)
                    except Exception as e:
                        logger.error(f"Failed to reset battery alarms:\n{e}")
                        self.bat = None
                    try:
                        if thermal_check(self.therm, self.bat, self.last_attempt, wakeup=True):
                            self.last_attempt = time.time()
                    except Exception as e:
                        logger.error(f"Failed to check thermal zones:\n{e}")
                        self.therm = {}
                        self.bat = None
                return


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [PowerPlugin()]
