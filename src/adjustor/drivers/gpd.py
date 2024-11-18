import logging
import os

from hhd.plugins import HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)


def handle_gpd_fix():
    logger.info("Received Hibernate Thermal event (spurious to get Windows to Hibernate), sleeping again.")
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

        if found:
            handle_gpd_fix()
