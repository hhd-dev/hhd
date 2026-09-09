import time
from threading import Event, Lock, Thread

from adjustor.core.fan import fan_worker, get_fan_info
from adjustor.core.rapl import RaplData, set_rapl
from hhd.plugins import Config, HHDPlugin, load_relative_yaml

APPLY_DELAY = 0.7
SLEEP_DELAY = 4.5
DEFAULT_FAN_CURVE = {
    40: 45, 45: 45, 50: 45, 55: 45, 60: 55,
    65: 60, 70: 70, 80: 85, 90: 100,
}


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
        self.fan_info = None
        self.fan_t = None
        self.fan_should_exit = Event()
        self.fan_junction = Event()
        self.fan_lock = Lock()
        self.fan_curve = {}
        self.fan_state = {}

    def open(self, emit, context):
        self.emit = emit
        self.fan_info = get_fan_info()

    def settings(self):
        if not self.enabled:
            return {}
        settings = load_relative_yaml("settings.yml")
        tdp = settings["children"]["tdp"]
        tdp.update(min=self.data.min_tdp, max=self.data.max_tdp,
                   default=self.data.default_tdp)
        if not self.data.pl2 and not self.data.pl4:
            del settings["children"]["boost"]
        if self.fan_info:
            children = settings["children"]["fan"]["modes"]["manual"]["children"]
            reset = children.pop("reset")
            for temp, speed in DEFAULT_FAN_CURVE.items():
                children[f"st{temp}"] = {
                    "type": "int", "title": f"{temp}C", "tags": ["slim"],
                    "min": 0, "max": 100, "step": 2, "unit": "%",
                    "default": speed,
                }
            children["reset"] = reset
        else:
            del settings["children"]["fan"]
        return {"tdp": {"intel": settings}}

    def update(self, conf: Config):
        enabled = conf.get("hhd.settings.tdp_ready", False)
        if enabled != self.enabled:
            self.enabled = enabled
            self.emit({"type": "settings"})
        if not enabled:
            self.close()
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
        self.update_fan(conf)

    def update_fan(self, conf: Config):
        if not self.fan_info or conf.get("tdp.intel.fan.mode", "disabled") != "manual":
            self.close()
            return

        base = "tdp.intel.fan.manual"
        with self.fan_lock:
            if conf.get(f"{base}.reset", False):
                conf[f"{base}.reset"] = False
                for temp, speed in DEFAULT_FAN_CURVE.items():
                    conf[f"{base}.st{temp}"] = speed
            self.fan_curve.clear()
            self.fan_curve.update({
                temp: min(100, max(0, conf.get(f"{base}.st{temp}", speed))) / 100
                for temp, speed in DEFAULT_FAN_CURVE.items()
            })
            if self.fan_state:
                s = self.fan_state
                fan_speed = (
                    f"{s['v_curr']*100:.1f}% @ {s['t_target']}C"
                    if s["in_setpoint"]
                    else f"{s['v_curr']*100:.1f}% → {s['v_target']*100:.1f}%"
                )
                conf[f"{base}.info"] = (
                    f"{fan_speed} ({', '.join(map(str, s['v_rpm']))} RPM)\n"
                    f"Temperature: {s['t_edge']:.2f}C\n"
                )

        if self.fan_t and not self.fan_t.is_alive():
            self.close()
        if not self.fan_t:
            self.fan_should_exit.clear()
            self.fan_t = Thread(
                target=fan_worker,
                args=(self.fan_info, self.fan_should_exit, self.fan_lock,
                      self.fan_curve, self.fan_state, self.fan_junction),
            )
            self.fan_t.start()

    def close(self):
        if self.fan_t:
            self.fan_should_exit.set()
            self.fan_t.join()
            self.fan_t = None
        self.fan_state.clear()

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
