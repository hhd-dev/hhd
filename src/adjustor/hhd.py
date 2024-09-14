import logging
import os
from threading import Event as TEvent
from threading import Thread
from typing import Sequence

from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config
from hhd.plugins.plugin import Emitter
from hhd.utils import expanduser

from adjustor.core.acpi import check_perms, initialize
from adjustor.core.const import CPU_DATA, DEV_DATA, PLATFORM_PROFILE_MAP, ENERGY_MAP

from .i18n import _

logger = logging.getLogger(__name__)

CONFLICTING_PLUGINS = {
    "SimpleDeckyTDP": "~/homebrew/plugins/SimpleDeckyTDP",
    "PowerControl": "~/homebrew/plugins/PowerControl",
}


class AdjustorInitPlugin(HHDPlugin):
    def __init__(self, use_acpi_call: bool = True) -> None:
        self.name = f"adjustor_init"
        self.priority = 5
        self.log = "adji"
        self.init = False
        self.failed = False
        self.has_decky = False
        self.enabled = False
        self.action_enabled = False
        self.use_acpi_call = use_acpi_call

    def open(self, emit: Emitter, context: Context):
        self.context = context
        self.emit = emit

    def settings(self):
        if self.enabled and not self.failed:
            self.action_enabled = False
            return {}
        self.action_enabled = True
        sets = {"tdp": {"tdp": load_relative_yaml("settings.yml")["tdp"]}}
        if not self.has_decky:
            del sets["tdp"]["tdp"]["children"]["decky_info"]
            del sets["tdp"]["tdp"]["children"]["decky_remove"]
        return sets

    def update(self, conf: Config):
        if (
            self.action_enabled
            and self.has_decky
            and conf["tdp.tdp.decky_remove"].to(bool)
        ):
            # Preparation
            logger.warning("Removing Decky plugins")
            conf["tdp.tdp.decky_remove"] = False
            conf["hhd.settings.tdp_enable"] = True
            self.has_decky = False
            self.failed = False

            move_path = expanduser("~/homebrew/plugins/hhd-disabled", self.context)
            if os.path.exists(move_path):
                logger.warning(f"Removing old backup path: '{move_path}'")
                os.system(f"rm -rf {move_path}")
            os.makedirs(
                move_path,
                exist_ok=True,
            )

            logger.warning("Stopping Decky.")
            try:
                os.system("systemctl stop plugin_loader")
            except Exception as e:
                logger.error(f"Failed to restart Decky:\n{e}")

            for name, ppath in CONFLICTING_PLUGINS.items():
                path = expanduser(ppath, self.context)
                if os.path.exists(path):
                    new_path = os.path.join(move_path, name)
                    logger.warning(
                        f"Moving plugin '{name}' from:\n{path}\nto:\n{new_path}"
                    )
                    os.rename(path, new_path)

            logger.warning("Restarting Decky.")
            try:
                os.system("systemctl start plugin_loader")
            except Exception as e:
                logger.error(f"Failed to restart Decky:\n{e}")

            # TDP controls are already enabled.
            logger.warning(f"Enabling TDP controls.")

        if self.action_enabled and conf["tdp.tdp.tdp_enable"].to(bool):
            conf["tdp.tdp.tdp_enable"] = False
            conf["hhd.settings.tdp_enable"] = True

        old_enabled = conf["hhd.settings.tdp_enable"].to(bool)
        if self.failed:
            conf["hhd.settings.tdp_enable"] = False

        self.enabled = conf["hhd.settings.tdp_enable"].to(bool)

        if self.init or not old_enabled:
            return

        for name, path in CONFLICTING_PLUGINS.items():
            if os.path.exists(expanduser(path, self.context)):
                err = f'Found "{name}" at:\n{path}\n' + _(
                    "Disable Decky TDP plugins using the button below to continue."
                )
                self.emit({"type": "settings"})
                self.has_decky = True
                conf["tdp.tdp.tdp_error"] = err
                conf["hhd.settings.tdp_enable"] = False
                logger.error(err)
                self.failed = True
                self.enabled = False
                return

        if self.use_acpi_call:
            initialize()
            if not check_perms():
                conf["hhd.settings.tdp_enable"] = False
                conf["tdp.tdp.tdp_error"] = (
                    "Can not write to 'acpi_call'. It is required for TDP."
                )
                self.failed = True
                self.enabled = False
                return

        self.failed = False
        self.enabled = True
        self.init = True
        conf["hhd.settings.tdp_enable"] = True
        conf["tdp.tdp.tdp_error"] = ""


class AdjustorPlugin(HHDPlugin):
    def __init__(self, min_tdp: int, default_tdp: int, max_tdp: int) -> None:
        self.name = f"adjustor_main"
        self.priority = 80
        self.log = "adjs"
        self.enabled = False
        self.enfoce_limits = True
        self.fuse_mount = False

        self.t = None
        self.t_sys = None
        self.should_exit = None

        self.min_tdp = min_tdp
        self.default_tdp = default_tdp
        self.max_tdp = max_tdp

    def settings(self) -> HHDSettings:
        out = {"hhd": {"settings": load_relative_yaml("settings.yml")["hhd"]}}
        if os.environ.get("HHD_ADJ_ENABLE_TDP"):
            out["hhd"]["settings"]["children"]["tdp_enable"]["default"] = True
        return out

    def _start(self):
        if self.should_exit:
            return
        self.should_exit = TEvent()
        if not self.t:
            try:
                from .events import loop_process_events

                self.t = Thread(
                    target=loop_process_events, args=(self.emit, self.should_exit)
                )
                self.t.start()
            except Exception as e:
                logger.warning(
                    f"Could not init ACPI event handling. Is pyroute2 installed?"
                )

        if self.fuse_mount and not self.t_sys:
            logger.info("Starting FUSE mount for /sys.")
            from .fuse import prepare_tdp_mount, start_tdp_client

            stat = prepare_tdp_mount()
            if stat:
                self.t_sys = start_tdp_client(
                    self.should_exit,
                    self.emit,
                    self.min_tdp,
                    self.default_tdp,
                    self.max_tdp,
                )

    def _stop(self):
        if not self.should_exit:
            return
        self.should_exit.set()
        if self.t:
            self.t.join()
            self.t = None
        if self.t_sys:
            self.t_sys.join()
            self.t_sys = None
        self.should_exit = None

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def update(self, conf: Config):
        new_enabled = conf["hhd.settings.tdp_enable"].to(bool)
        new_enforce_limits = conf["hhd.settings.enforce_limits"].to(bool)
        if new_enabled != self.enabled or new_enforce_limits != self.enfoce_limits:
            self.emit({"type": "settings"})
        self.fuse_mount = conf["hhd.settings.fuse_mount"].to(bool)
        self.enabled = new_enabled
        self.enfoce_limits = new_enforce_limits

        if self.enabled:
            self._start()
        else:
            self._stop()

    def close(self):
        self._stop()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    from .drivers.asus import AsusDriverPlugin
    from .drivers.lenovo import LenovoDriverPlugin
    from .drivers.smu import SmuDriverPlugin, SmuQamPlugin
    from .drivers.amd import AmdGPUPlugin

    drivers = []
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        prod = f.read().strip()
    with open("/proc/cpuinfo") as f:
        cpuinfo = f.read().strip()

    use_acpi_call = False
    drivers_matched = False

    # FIXME: Switch to per device
    # But all devices use the same values
    # pretty much
    min_tdp = 4
    default_tdp = 15
    max_tdp = 30

    if prod == "83E1" and not bool(os.environ.get("HHD_ADJ_ALLY")):
        drivers.append(LenovoDriverPlugin())
        drivers_matched = True
        use_acpi_call = True

    if (
        "ROG Ally RC71L" in prod
        or "ROG Ally X RC72L" in prod
        or bool(os.environ.get("HHD_ADJ_DEBUG"))
        or bool(os.environ.get("HHD_ADJ_ALLY"))
    ):
        drivers.append(AsusDriverPlugin("RC72L" in prod))
        drivers_matched = True
        min_tdp = 7

    if os.environ.get("HHD_ADJ_DEBUG") or os.environ.get("HHD_ENABLE_SMU"):
        drivers_matched = False

    if not drivers_matched and prod in DEV_DATA:
        dev, cpu, pp_enable = DEV_DATA[prod]

        try:
            # Set values for the steam slider
            if dev["skin_limit"].smin:
                min_tdp = dev["skin_limit"].smin
            if dev["skin_limit"].default:
                default_tdp = dev["skin_limit"].default
            if dev["skin_limit"].smax:
                max_tdp = dev["skin_limit"].smax
        except Exception as e:
            logger.error(f"Failed to get TDP limits for {prod}:\n{e}")

        pp_enable |= bool(os.environ.get("HHD_ADJ_DEBUG"))
        drivers.append(
            SmuDriverPlugin(
                dev,
                cpu,
                platform_profile=pp_enable,
            )
        )
        drivers.append(
            SmuQamPlugin(
                dev,
                PLATFORM_PROFILE_MAP if pp_enable else None,
                ENERGY_MAP,
                init_tdp=not prod == "83E1",
            ),
        )
        drivers_matched = True
        use_acpi_call = True

    if not drivers_matched:
        for name, (dev, cpu) in CPU_DATA.items():
            if name in cpuinfo:
                drivers.append(
                    SmuDriverPlugin(
                        dev,
                        cpu,
                        platform_profile=True,
                    )
                )
                drivers.append(
                    SmuQamPlugin(dev, PLATFORM_PROFILE_MAP, ENERGY_MAP),
                )
                use_acpi_call = True
                break

    if not drivers:
        from .drivers.general import GeneralPowerPlugin

        logger.info(f"No tdp drivers found for this device, using generic plugin.")
        
        is_steamdeck = "Jupiter" in prod or "Galileo" in prod
        return [GeneralPowerPlugin(is_steamdeck=is_steamdeck)]

    return [
        *drivers,
        AdjustorInitPlugin(use_acpi_call=use_acpi_call),
        AdjustorPlugin(min_tdp, default_tdp, max_tdp),
        AmdGPUPlugin(),
    ]
