import logging
from typing import Sequence


from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config
from hhd.plugins.settings import load_state_yaml, save_state_yaml, get_settings_hash


logger = logging.getLogger(__name__)


class AdjustorPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor"
        self.priority = 4
        self.log = "adjs"
        logger.info("Adjustor Plugin Loaded")
        self.last_conf = self.settings()["Adjustor"]

    def settings(self) -> HHDSettings:
        settings = load_relative_yaml("settings.yml")
        self.ensure_type_key(settings)
        return {"Adjustor": settings}

    def ensure_type_key(self, settings_dict):
        if not isinstance(settings_dict, dict):
            logger.warning(
                f"Expected a dict in ensure_type_key, got {type(settings_dict)}"
            )
            return

        for key, value in settings_dict.items():
            if isinstance(value, dict):
                if "type" not in value:
                    value["type"] = "default"  # Set a default type if missing
                if "children" in value:
                    self.ensure_type_key(value["children"])

    def open(self, emit, context: Context):
        # Intiialization logic when the plugin is loaded
        pass

    def find_changed_keys(self, old_conf, new_conf, parent_key=""):
        if not isinstance(new_conf, dict) or not isinstance(new_conf, dict):
            logger.warning(
                f"Expected a dict in find_changed_keys, got {type(new_conf)}"
            )
            return {}
        changed_keys = {}
        for section, settings in new_conf.items():
            full_key = f"{parent_key}.{section}" if parent_key else section
            if section not in old_conf:
                continue  # Skip if the section is new
            if isinstance(settings, dict) and "children" in settings:
                # Recurse into container's children
                children = settings["children"]
                old_children = old_conf[section].get("children", {})
                nested_changes = self.find_changed_keys(
                    old_children, children, full_key
                )
                changed_keys.update(nested_changes)
            elif "value" in settings:  # Check for changed value
                new_value = settings.get("value", None)  # Get the new value
                old_value = old_conf[section].get(
                    "value", None
                )  # Get the old value safely
                if new_value != old_value:
                    changed_keys[full_key] = new_value
        return changed_keys

    def update(self, conf: Config):
        curr_conf = self.settings().get("Adjustor", {})
        if not isinstance(curr_conf, dict):
            logger.error("Current configuration is not a dictionary.")
            return
        tdp_management = curr_conf.get("tdp_management", {}).get("children", {})
        tdp_fast = tdp_management.get("tdp_fast", {}).get("value", None)
        tdp_slow = tdp_management.get("tdp_slow", {}).get("value", None)
        tdp_steady = tdp_management.get("tdp_steady", {}).get("value", None)
        tdp_mode = tdp_management.get("tdp_mode", {}).get("value", None)

        logger.info(f"Current tdp_fast: {tdp_fast}")
        logger.info(f"Current tdp_slow: {tdp_slow}")
        logger.info(f"Current tdp_steady: {tdp_steady}")
        logger.info(f"Current tdp mode: {tdp_mode}")

        changed_keys = self.find_changed_keys(self.last_conf, curr_conf)
        for key, value in changed_keys.items():
            if key in [
                "tdp_management.tdp_fast",
                "tdp_management.tdp_slow",
                "tdp_management.tdp_steady",
            ]:
                self.handle_tdp_change(key, value)
        self.last_conf = curr_conf

    def handle_power_mode(self, mode):
        if mode not in ["quiet", "balanced", "performance", "custom"]:
            logger.error(f"Invalid power mode: {mode}")
            return
        # Load current config
        settings_path = "/home/deck/adjustor/src/adjustor/settings.yml"
        settings = load_state_yaml(settings_path, {})

        if not isinstance(settings, dict):
            logger.error("Settings data is not a dictionary.")
            return

        tdp_mode = (
            settings.get("tdp_management", {})
            .get("children", {})
            .get("tdp_mode", {})
            .get("value", None)
        )
        if tdp_mode == "ryzenadj":
            logger.info("Ryzenadj mode")
            if mode == "quiet":
                # ryzenadj.set_tdp_fast(10)
                # ryzenadj.set_tdp_slow(10)
                # ryzenadj.set_tdp_steady(10)
                pass
            elif mode == "balanced":
                # ryzenadj.set_tdp_fast(20)
                # ryzenadj.set_tdp_slow(20)
                # ryzenadj.set_tdp_steady(20)
                pass
            elif mode == "performance":
                # ryzenadj.set_tdp_fast(30)
                # ryzenadj.set_tdp_slow(30)
                # ryzenadj.set_tdp_steady(30)
                pass
            elif mode == "custom":
                pass
            else:
                logger.error(f"Invalid power mode: {mode}")
                return
            # Perhaps here we can establish some generic profiles in for devices that don't have a specific library yet, this way we can still have some functionality for profiles. i.e "quiet", "balanced", "performance"
            # Quiet: tdp_fast = 10, tdp_slow = 10, tdp_steady = 10
            # Balanced: tdp_fast = 20, tdp_slow = 20, tdp_steady = 20
            # Performance: tdp_fast = 30, tdp_slow = 30, tdp_steady = 30

            # Then set this using ryzenadj

        elif tdp_mode == "legiongo":
            logger.info("LegionGo mode")
            # Legion GO must be in custom mode for TDP management to work
            current_mode = lg.get_smart_fan_mode()
            logger.info(f"Current mode: {current_mode}")
            lg.set_smart_fan_mode(
                {"quiet": 1, "balanced": 2, "performance": 3, "custom": 255}[mode]
            )

        settings["tdp_management"]["children"]["tdp_mode"]["children"]["manufacturer"][
            "legion_go"
        ]["powermode"] = {"value": mode}
        # Save the modified settings back to the YAML
        save_state_yaml(settings_path, {}, settings)

    def handle_tdp_change(self, key, value):
        tdp_mode = (
            self.last_conf.get("tdp_management", {})
            .get("children", {})
            .get("tdp_mode", {})
            .get("value", None)
        )
        self.handle_power_mode("custom")

        if tdp_mode == "ryzenadj":
            logger.info("Ryzenadj mode")  # Example code for Ryzenadj
            if key.endswith("tdp_fast"):
                logger.info(f"Changing TDP Fast to {value}")
                # ryzenadj.set_tdp_fast(value)  # Example call to ryzenadj library
            elif key.endswith("tdp_slow"):
                logger.info(f"Changing TDP Slow to {value}")
                # ryzenadj.set_tdp_slow(value)  # Example call to ryzenadj library
            elif key.endswith("tdp_steady"):
                logger.info(f"Changing TDP Steady to {value}")
                # ryzenadj.set_tdp_steady(value)  # Example call to ryzenadj library

        elif tdp_mode == "legiongo":
            logger.info("LegionGo mode")
            # Legion GO must be in custom mode for TDP management to work
            current_mode = lg.get_smart_fan_mode()
            if "0xff" not in current_mode:
                self.handle_power_mode("custom")
                logger.info("Not in Custom Mode, changing to Custom Mode")
            else:
                logger.info("Already in Custom Mode")

            if key.endswith("tdp_fast"):
                logger.info(f"Changing TDP Fast to {value}")
                lg.set_tdp_value("fast", value)
            elif key.endswith("tdp_slow"):
                logger.info(f"Changing TDP Slow to {value}")
                lg.set_tdp_value("slow", value)
            elif key.endswith("tdp_steady"):
                logger.info(f"Changing TDP Steady to {value}")
                lg.set_tdp_value("steady", value)

    def close(self):
        pass  # Cleanup logic for when the plugin is closed or the HHD service is shutting down.


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [AdjustorPlugin()]
