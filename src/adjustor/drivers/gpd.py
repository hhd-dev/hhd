import logging
import os
import time

from hhd.plugins import HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)


def handle_gpd_fix():
    logger.info(
        "Received Hibernate Thermal event (spurious to get Windows to Hibernate), sleeping again."
    )

    # Wait for suspend.target to finish
    # While active it returns 0
    for _ in range(250):
        if os.system("systemctl is-active --quiet suspend.target"):
            break
        time.sleep(0.2)
    
    # Give it a bit of time, otherwise the EC will keep waking up the device
    time.sleep(5)

    try:
        with open("/sys/bus/acpi/devices/LNXTHERM:00/thermal_zone/temp", "r") as f:
            temp = int(f.read().strip())
            logger.info(f"Thermal zone temp: {temp}")
    except Exception as e:
        logger.error(f"Failed to read thermal zone temp: {e}")
        temp = 0

    if temp == 105_000:
        logger.info("Fake temperature detected.")
        os.system("systemctl suspend")


class GpdFixPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_gpd_fix"
        self.priority = 50
        self.log = "gpdf"
        self.enabled = False
        self.global_enabled = False

    def settings(self) -> HHDSettings:
        # Settings change notification
        # is sent by other plugins
        if self.global_enabled:
            return load_relative_yaml("gpd.yml")
        return {}

    def update(self, conf: Config):
        self.global_enabled = conf.get("hhd.settings.tdp_enable", False)
        self.enabled = conf.get("hhd.settings.gpd_wakeup_fix", False)

    def notify(self, events):
        if not self.enabled:
            return

        found = False
        for ev in events:
            if ev.get("type") == "acpi" and ev.get("event") == "hibernate-thermal":
                found = True
                break

        # if found:
        #     handle_gpd_fix()
