import time

from adjustor.core.rapl import RaplData, set_rapl
from hhd.plugins import Config, HHDPlugin, load_relative_yaml

APPLY_DELAY = 0.7
SLEEP_DELAY = 4.5


class IntelDriverPlugin(HHDPlugin):
    def __init__(self, data: RaplData):
        self.name = "adjustor_intel_qam"
        self.priority = 7
        self.log = "intq"
        self.data = data
        self.enabled = False
        self.old_boost = None
        self.old_tdp = None
        self.new_tdp = None
        self.queue_tdp = None
        self.sys_tdp = False
        self.error = ""

    def open(self, emit, context):
        self.emit = emit

    def settings(self):
        if not self.enabled:
            return {}
        settings = load_relative_yaml("settings.yml")
        tdp = settings["children"]["tdp"]
        tdp.update(min=self.data.min_tdp, max=self.data.max_tdp,
                   default=self.data.default_tdp)
        if not self.data.pl2 and not self.data.pl4:
            del settings["children"]["boost"]
        return {"tdp": {"intel": settings}}

    def update(self, conf: Config):
        enabled = conf.get("hhd.settings.tdp_ready", False)
        if enabled != self.enabled:
            self.enabled = enabled
            self.emit({"type": "settings"})
        if not enabled:
            self.old_boost = None
            self.old_tdp = None
            self.queue_tdp = None
            self.new_tdp = None
            return

        requested = conf.get("tdp.intel.tdp", self.data.default_tdp)
        if self.new_tdp is not None:
            requested = self.new_tdp
            self.new_tdp = None
        elif self.old_tdp is not None and requested != self.old_tdp:
            self.sys_tdp = False
        watts = min(max(int(requested), self.data.min_tdp), self.data.max_tdp)
        conf["tdp.intel.tdp"] = watts
        boost = conf.get("tdp.intel.boost", True)
        now = time.perf_counter()
        if watts != self.old_tdp or boost != self.old_boost:
            self.old_tdp = watts
            self.old_boost = boost
            self.queue_tdp = max(self.queue_tdp or 0, now + APPLY_DELAY)
        if self.queue_tdp is not None and now >= self.queue_tdp:
            self.queue_tdp = None
            self.error = "" if set_rapl(self.data, watts, boost) else (
                "Could not write Intel RAPL limits. Check permissions and firmware locks."
            )
        conf["tdp.intel.error"] = self.error
        conf["hhd.steamos.tdp_status"] = "conflict" if self.error else "enabled"
        conf["hhd.steamos.tdp_set"] = self.sys_tdp and watts != self.data.max_tdp

    def notify(self, events):
        for ev in events:
            if ev["type"] == "tdp":
                self.new_tdp = ev["tdp"]
                self.sys_tdp = ev["tdp"] is not None
            elif ev["type"] == "special" and ev.get("event") == "wakeup":
                self.queue_tdp = time.perf_counter() + SLEEP_DELAY
            elif ev["type"] == "acpi" and ev.get("event") in ("ac", "dc"):
                self.queue_tdp = max(
                    self.queue_tdp or 0, time.perf_counter() + APPLY_DELAY
                )
