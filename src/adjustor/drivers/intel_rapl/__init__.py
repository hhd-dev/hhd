import logging
import os
import shutil
import subprocess
import time
from typing import Sequence

from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml

logger = logging.getLogger(__name__)

MSR_RAPL_POWER_UNIT = 0x606
MSR_PKG_POWER_LIMIT = 0x610

PL1_POWER_MASK = 0x7FFF
PKG_POWER_LIMIT_LOCK = 1 << 63

MSR_DEVICE = "/dev/cpu/0/msr"
DMI_PRODUCT = "/sys/devices/virtual/dmi/id/product_name"
CPUINFO = "/proc/cpuinfo"

EXPECTED_PRODUCT = "ONEXPLAYER 3"
MIN_TDP = 8
DEFAULT_TDP = 25
MAX_TDP = 35

APPLY_DELAY = 0.7
SLEEP_DELAY = 4.0


def get_power_exponent(rapl_units: int) -> int:
    """Return the Intel RAPL power-unit exponent from MSR 0x606."""
    exponent = rapl_units & 0xF
    if exponent > 8:
        raise ValueError(f"Unexpected RAPL power-unit exponent: {exponent}")
    return exponent


def watts_to_raw(watts: int, exponent: int) -> int:
    """Encode an integer watt value for the 15-bit PL1 power field."""
    raw = int(watts) * (1 << exponent)
    if raw < 0 or raw > PL1_POWER_MASK:
        raise ValueError(f"PL1 raw value 0x{raw:x} does not fit in 15 bits")
    return raw


def replace_pl1_power(msr_value: int, raw_pl1: int) -> int:
    """Replace only MSR_PKG_POWER_LIMIT bits 14:0."""
    if raw_pl1 < 0 or raw_pl1 > PL1_POWER_MASK:
        raise ValueError(f"PL1 raw value 0x{raw_pl1:x} does not fit in 15 bits")
    return (msr_value & ~PL1_POWER_MASK) | raw_pl1


class IntelRaplDriverPlugin(HHDPlugin):
    """Intel RAPL PL1 backend for the Intel ONEXPLAYER 3."""

    def __init__(self) -> None:
        self.name = "adjustor_intel_rapl"
        self.priority = 6
        self.log = "irap"

        self.available = False
        self.last_tdp: int | None = None
        self.pending_tdp: int | None = None
        self.reapply_at: float | None = None

    @staticmethod
    def _read_text(path: str) -> str:
        with open(path) as f:
            return f.read().strip()

    @staticmethod
    def _ensure_msr_device() -> bool:
        if os.path.exists(MSR_DEVICE):
            return True

        modprobe = shutil.which("modprobe") or "/usr/bin/modprobe"
        try:
            subprocess.run(
                [modprobe, "msr"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            logger.error("Failed loading Intel 'msr' module: %s", exc)
            return False

        return os.path.exists(MSR_DEVICE)

    @staticmethod
    def _read_msr(register: int) -> int:
        fd = os.open(MSR_DEVICE, os.O_RDONLY)
        try:
            value = os.pread(fd, 8, register)
        finally:
            os.close(fd)

        if len(value) != 8:
            raise OSError(
                f"Short MSR read at 0x{register:x}: "
                f"expected 8 bytes, got {len(value)}"
            )

        return int.from_bytes(value, "little", signed=False)

    @staticmethod
    def _write_msr(register: int, value: int) -> None:
        fd = os.open(MSR_DEVICE, os.O_WRONLY)
        try:
            written = os.pwrite(fd, value.to_bytes(8, "little"), register)
        finally:
            os.close(fd)

        if written != 8:
            raise OSError(
                f"Short MSR write at 0x{register:x}: "
                f"expected 8 bytes, wrote {written}"
            )

    @classmethod
    def _restore_pl1(cls, previous_raw: int) -> None:
        current = cls._read_msr(MSR_PKG_POWER_LIMIT)

        if current & PKG_POWER_LIMIT_LOCK:
            logger.error("MSR_PKG_POWER_LIMIT locked before PL1 rollback.")
            return

        cls._write_msr(
            MSR_PKG_POWER_LIMIT,
            replace_pl1_power(current, previous_raw),
        )

    def _probe(self) -> tuple[int, int] | None:
        try:
            if self._read_text(DMI_PRODUCT) != EXPECTED_PRODUCT:
                return None

            if "GenuineIntel" not in self._read_text(CPUINFO):
                return None

            if not self._ensure_msr_device():
                return None

            exponent = get_power_exponent(self._read_msr(MSR_RAPL_POWER_UNIT))
            package_limit = self._read_msr(MSR_PKG_POWER_LIMIT)

            if package_limit & PKG_POWER_LIMIT_LOCK:
                logger.error(
                    "MSR_PKG_POWER_LIMIT is locked; TDP control unavailable."
                )
                return None

            return exponent, package_limit
        except Exception as exc:
            logger.error("Intel RAPL probe failed: %s", exc)
            return None

    def is_supported(self) -> bool:
        return self._probe() is not None

    def open(self, emit, context: Context):
        probed = self._probe()
        if not probed:
            self.available = False
            return

        exponent, package_limit = probed
        pl1_raw = package_limit & PL1_POWER_MASK
        pl1 = pl1_raw / float(1 << exponent)

        logger.info(
            "ONEXPLAYER 3 Intel RAPL backend ready: "
            "unit=1/%d W, PL1=%.3f W, range=%d-%d W",
            1 << exponent,
            pl1,
            MIN_TDP,
            MAX_TDP,
        )
        self.available = True

    def settings(self):
        return {"tdp": {"intel_rapl": load_relative_yaml("settings.yml")}}

    def _set_tdp(self, watts: int) -> bool:
        if not self.available:
            return False

        watts = int(watts)
        if watts < MIN_TDP or watts > MAX_TDP:
            logger.warning(
                "Rejecting ONEXPLAYER 3 PL1=%d W outside %d-%d W.",
                watts,
                MIN_TDP,
                MAX_TDP,
            )
            return False

        previous_raw: int | None = None

        try:
            exponent = get_power_exponent(self._read_msr(MSR_RAPL_POWER_UNIT))
            requested_raw = watts_to_raw(watts, exponent)

            old = self._read_msr(MSR_PKG_POWER_LIMIT)

            if old & PKG_POWER_LIMIT_LOCK:
                logger.error(
                    "MSR_PKG_POWER_LIMIT became locked; refusing PL1 write."
                )
                self.available = False
                return False

            previous_raw = old & PL1_POWER_MASK

            if previous_raw == requested_raw:
                self.last_tdp = watts
                return True

            new = replace_pl1_power(old, requested_raw)
            self._write_msr(MSR_PKG_POWER_LIMIT, new)

            verify = self._read_msr(MSR_PKG_POWER_LIMIT)
            verify_raw = verify & PL1_POWER_MASK

            if verify_raw != requested_raw:
                logger.error(
                    "PL1 verification failed: requested=0x%x, read=0x%x. "
                    "Restoring previous PL1.",
                    requested_raw,
                    verify_raw,
                )
                self._restore_pl1(previous_raw)
                return False

            self.last_tdp = watts
            logger.info(
                "ONEXPLAYER 3 PL1 set to %d W: "
                "MSR 0x610 0x%016x -> 0x%016x",
                watts,
                old,
                verify,
            )
            return True

        except Exception:
            logger.exception("Failed setting ONEXPLAYER 3 Intel RAPL PL1.")

            if previous_raw is not None:
                try:
                    self._restore_pl1(previous_raw)
                except Exception:
                    logger.exception("Failed restoring previous PL1.")

            return False

    def update(self, conf: Config):
        if not conf["hhd.settings.tdp_ready"].to(bool) or not self.available:
            return

        if self.pending_tdp is not None:
            target = self.pending_tdp
            self.pending_tdp = None
            conf["tdp.intel_rapl.tdp"] = target
        else:
            target = conf["tdp.intel_rapl.tdp"].to(int)

        target = max(MIN_TDP, min(MAX_TDP, target))

        if target != conf["tdp.intel_rapl.tdp"].to(int):
            conf["tdp.intel_rapl.tdp"] = target

        now = time.perf_counter()
        timed_reapply = self.reapply_at is not None and now >= self.reapply_at

        if timed_reapply:
            self.reapply_at = None

        if self.last_tdp != target or timed_reapply:
            self._set_tdp(target)

    def notify(self, events: Sequence[Event]):
        for event in events:
            if event["type"] == "tdp":
                requested = event.get("tdp")
                if requested is None:
                    continue

                requested = int(requested)
                if MIN_TDP <= requested <= MAX_TDP:
                    self.pending_tdp = requested
                else:
                    logger.warning(
                        "Ignoring external TDP event %d W outside %d-%d W.",
                        requested,
                        MIN_TDP,
                        MAX_TDP,
                    )

            elif event["type"] == "special" and event.get("event") == "wakeup":
                logger.info(
                    "Waking from sleep; reapplying ONEXPLAYER 3 PL1 "
                    "after %.1f seconds.",
                    SLEEP_DELAY,
                )
                self.reapply_at = time.perf_counter() + SLEEP_DELAY

            elif (
                event["type"] == "acpi"
                and event.get("event") in ("ac", "dc")
                and self.reapply_at is None
            ):
                logger.info(
                    "Power adapter status switched to '%s'; reapplying PL1.",
                    event["event"],
                )
                self.reapply_at = time.perf_counter() + APPLY_DELAY
