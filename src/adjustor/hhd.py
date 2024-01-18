import logging
import os
from time import sleep
from typing import TYPE_CHECKING, Any, Sequence

import yaml

from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config
import adjustor.legiongo as lg # Default Legion Go library
# Should we create a new library for every device? 

logger = logging.getLogger(__name__)

def write_sysfs(dir: str, fn: str, val: Any):
    with open(os.path.join(dir, fn), "w") as f:
        f.write(str(val))


def read_sysfs(dir: str, fn: str, default: str | None = None):
    try:
        with open(os.path.join(dir, fn), "r") as f:
            return f.read().strip()
    except Exception as e:
        if default is not None:
            return default
        raise e


class AdjustorPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor"
        self.priority = 4
        self.log = "adjs"


        self.tdp_default = None

        self.tdp_max = None
        self.tdp_min = None
        self.tdp_step = None # To be used for autoTDP

        self.tdp = None
        self.tdp_slow = None
        self.tdp_fast = None

        self.display = None
        self.max_brightness = 255

        print("Adjustor Plugin Loaded")
        logger.info("Adjustor Plugin Loaded")
        self.last_conf = None

    def settings(self) -> HHDSettings:
        return {"Adjustor": {"adjustor": load_relative_yaml("settings.yml")}}

    def open(
        self,
        emit,
        context: Context,
    ):
        logger.info("Adjustor Plugin Opened")
        # Intiialization logic when the plugin is loaded
        pass

    def apply_setting_change(self, setting_name: str, new_value: Any):
        # This method takes the settings name and the new value to apply
        if hasattr(self, setting_name):
            current_value = getattr(self, setting_name)
            logger.info(f"Current value for {setting_name}: {current_value}")
            if current_value != new_value:
                setattr(self, setting_name, new_value)
                logger.info(f"Updated setting {setting_name} changed to: {new_value}")
                # Call method 
        else:
            logger.warning(f"Setting {setting_name} not found on the plugin")


    def update(self, conf: Config):
        # Logic to handle configuration updates; this is where you would check for changes and react accordingly.        
        new_conf = self.settings()["Adjustor"]["adjustor"]
        # logger.info(f"Current status for Max TDP: {new_conf["tdp"]["max_tdp"]["value"]}")
        
        if new_conf != self.last_conf:
            self.last_conf = conf
            for section_key, section_value in new_conf.items():
                logger.info(f"Section Key: {section_key} Value: {section_value}")
                if section_key in self.last_conf and self.last_conf[section_key] != section_value:
                    for setting_key, setting_value in section_value.items():
                        logger.info(f"Setting Key: {setting_key} Value: {setting_value}")
                        self.apply_setting_change(section_key, setting_key, setting_value['value'])
            self.last_conf = new_conf
            logger.info("Settings Updated")

            # Update the TDP
            # tdp_section = conf["tdp_mode.adjustor"]
            # mode = tdp_section["mode"].to(str)
            # wattage = tdp_section["wattage"].to(int)
            # legiongo.set_tdp_value(mode, wattage)
        
        pass

    def close(self):
        # Cleanup logic for when the plugin is closed or the HHD service is shutting down.
        pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [AdjustorPlugin()]
