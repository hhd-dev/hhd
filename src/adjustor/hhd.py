import logging
import os
from threading import Event as TEvent, Thread
from typing import Sequence

from hhd.utils import expanduser
from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config
from hhd.plugins.plugin import Emitter

from adjustor.core.acpi import check_perms, initialize
from adjustor.core.const import CPU_DATA, DEV_DATA, ROG_ALLY_PP_MAP

from .utils import exists_sentinel, install_sentinel, remove_sentinel

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
        self.safe_mode = False
        self.enabled = False
        self.action_enabled = False
        self.use_acpi_call = use_acpi_call

    def open(self, emit: Emitter, context: Context):
        self.context = context
        if exists_sentinel() or not install_sentinel():
            self.safe_mode = True

    def settings(self):
        if self.enabled and not self.failed:
            self.action_enabled = False
            return {}
        self.action_enabled = True
        return {"tdp": {"tdp": load_relative_yaml("settings.yml")["tdp"]}}

    def update(self, conf: Config):
        if self.action_enabled and conf["tdp.tdp.tdp_enable"].to(bool):
            conf["tdp.tdp.tdp_enable"] = False
            conf["hhd.settings.tdp_enable"] = True

        old_enabled = conf["hhd.settings.tdp_enable"].to(bool)
        if self.failed:
            conf["hhd.settings.tdp_enable"] = False
        if self.safe_mode:
            logger.warning(f"Due to a sentinel error, auto-start is disabled.")
            conf["tdp.tdp.tdp_error"] = (
                "Due to a suspected crash, auto-start was disabled."
            )
            conf["hhd.settings.tdp_enable"] = False
            self.safe_mode = False

        self.enabled = conf["hhd.settings.tdp_enable"].to(bool)

        if self.init or not old_enabled:
            return

        for name, path in CONFLICTING_PLUGINS.items():
            if os.path.exists(expanduser(path, self.context)):
                err = (
                    f'Found plugin "{name}" at the following path:\n{path}\n'
                    + "TDP Controls can not be enabled while other TDP plugins are installed."
                )
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

    def close(self):
        remove_sentinel()


class AdjustorPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_main"
        self.priority = 80
        self.log = "adjs"
        self.enabled = False
        self.enfoce_limits = True

        self.t = None
        self.should_exit = None

    def settings(self) -> HHDSettings:
        out = {"hhd": {"settings": load_relative_yaml("settings.yml")["hhd"]}}
        if os.environ.get("HHD_ADJ_ENABLE_TDP"):
            out["hhd"]["settings"]["children"]["tdp_enable"]["default"] = True
        return out

    def _start(self):
        if self.should_exit or self.t:
            return
        try:
            from .events import loop_process_events

            self.should_exit = TEvent()
            self.t = Thread(
                target=loop_process_events, args=(self.emit, self.should_exit)
            )
            self.t.start()
        except Exception as e:
            logger.warning(
                f"Could not init ACPI event handling. Is pyroute2 installed?"
            )

    def _stop(self):
        if not self.should_exit or not self.t:
            return
        self.should_exit.set()
        self.t.join()
        self.should_exit = None
        self.t = None

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

    from .drivers.lenovo import LenovoDriverPlugin
    from .drivers.asus import AsusDriverPlugin
    from .drivers.smu import SmuDriverPlugin, SmuQamPlugin

    drivers = []
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        prod = f.read().strip()
    with open("/proc/cpuinfo") as f:
        cpuinfo = f.read().strip()

    use_acpi_call = False
    drivers_matched = False
    if prod == "83E1":
        drivers.append(LenovoDriverPlugin())
        drivers_matched = True
        use_acpi_call = True

    if "ROG Ally RC71L" in prod:
        drivers.append(AsusDriverPlugin())
        drivers_matched = True

    if os.environ.get("HHD_ADJ_DEBUG") or os.environ.get("HHD_ENABLE_SMU"):
        drivers_matched = False

    if not drivers_matched and prod in DEV_DATA:
        dev, cpu, pp_enable = DEV_DATA[prod]
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
                dev, ROG_ALLY_PP_MAP if pp_enable else None, init_tdp=not prod == "83E1"
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
                    SmuQamPlugin(dev, ROG_ALLY_PP_MAP),
                )
                use_acpi_call = True
                break

    if not drivers:
        logger.info(f"No tdp drivers found for this device, exiting Adjustor.")
        return []

    return [
        *drivers,
        AdjustorInitPlugin(use_acpi_call=use_acpi_call),
        AdjustorPlugin(),
    ]
