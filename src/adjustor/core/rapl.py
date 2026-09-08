"""Intel package power limits through the Linux powercap interface."""

import logging
from pathlib import Path
from typing import NamedTuple

from .const import INTEL_TDP_PRESETS

logger = logging.getLogger(__name__)
POWERCAP = Path("/sys/class/powercap")
UW_PER_W = 1_000_000


class RaplLimit(NamedTuple):
    path: Path
    max_tdp: int


class RaplData(NamedTuple):
    limits: tuple[Path, ...]
    min_tdp: int
    default_tdp: int
    max_tdp: int
    pl2: tuple[RaplLimit, ...] = ()
    pl4: tuple[RaplLimit, ...] = ()


def get_rapl(board: str = "") -> RaplData | None:
    """Discover one package, including its independently enforced MMIO cap.

    Never use core, uncore, DRAM or whole-system (psys) domains as TDP.
    Discovery is read-only; firmware locks can still reject a later write.
    """
    preset = INTEL_TDP_PRESETS.get(board, None)
    limits = []
    maxima = []
    packages = set()
    boost_limits = {"short_term": [], "peak_power": []}
    for zone in sorted(POWERCAP.glob("intel-rapl*:*")):
        try:
            name = (zone / "name").read_text().strip()
            if not name.startswith("package-"):
                continue
            packages.add(name)
            if (zone / "enabled").read_text().strip() != "1":
                continue
            zone_limits = {}
            for constraint in sorted(zone.glob("constraint_*_name")):
                try:
                    kind = constraint.read_text().strip()
                    if kind not in ("long_term", "short_term", "peak_power"):
                        continue
                    prefix = constraint.name.removesuffix("name")
                    limit = zone / f"{prefix}power_limit_uw"
                    current = int(limit.read_text())
                    if current <= 0 or not limit.stat().st_mode & 0o222:
                        continue
                    try:
                        maximum = int((zone / f"{prefix}max_power_uw").read_text())
                    except (OSError, ValueError):
                        maximum = 0
                    # Without a reported ceiling, use the startup cap as fallback.
                    maximum = (maximum if maximum > 0 else current) // UW_PER_W
                    if preset:
                        if kind == "long_term":
                            maximum = preset["pl1"]
                        elif kind == "short_term":
                            maximum = preset["pl2"]
                        else:
                            maximum = max(preset["pl2"], maximum)
                    if maximum > 0:
                        zone_limits[kind] = (limit, maximum)
                except (OSError, ValueError):
                    continue
            if "long_term" not in zone_limits:
                continue
            limit, maximum = zone_limits["long_term"]
            limits.append(limit)
            maxima.append(maximum)
            for kind, values in boost_limits.items():
                if kind in zone_limits:
                    path, ceiling = zone_limits[kind]
                    values.append(RaplLimit(path, ceiling))
        except (OSError, ValueError):
            continue

    minimum = 5
    default = 15
    if preset:
        if "minTdp" in preset:
            minimum = preset["minTdp"]
        if "defaultTdp" in preset:
            default = preset["defaultTdp"]
    # A single slider has no per-socket semantics.
    if len(packages) != 1 or not limits or min(maxima) < 5:
        return None
    maximum = min(maxima)
    return RaplData(
        tuple(limits), minimum, default, maximum,
        tuple(boost_limits["short_term"]), tuple(boost_limits["peak_power"]),
    )


def set_rapl(data: RaplData, watts: int, boost: bool = True) -> bool:
    if not data.min_tdp <= watts <= data.max_tdp:
        raise ValueError(f"RAPL limit outside {data.min_tdp}-{data.max_tdp} W")
    targets = [(path, watts) for path in data.limits]
    power_limits = {"PL1": [watts], "PL2": [], "PL4": []}
    for limit in data.pl2:
        value = min(watts + 2 if boost else watts, limit.max_tdp)
        targets.append((limit.path, value))
        power_limits["PL2"].append(value)
    for limit in data.pl4:
        value = watts * limit.max_tdp // data.max_tdp if boost else watts
        value = min(value, limit.max_tdp)
        targets.append((limit.path, value))
        power_limits["PL4"].append(value)
    previous = []
    try:
        # Read every cap before changing any of them, for rollback on failure.
        snapshots = [(path, path.read_text(), target) for path, target in targets]
        for path, value, target in snapshots:
            path.write_text(f"{target * UW_PER_W}\n")
            previous.append((path, value))
        summary = ", ".join(
            f"{name} to {'/'.join(str(v) for v in dict.fromkeys(values))} W"
            for name, values in power_limits.items() if values
        )
        logger.info(f"Set Intel package {summary} (boost={boost}).")
        return True
    except OSError as e:
        logger.error(f"Could not set Intel RAPL limit: {e}")
        for path, value in reversed(previous):
            try:
                path.write_text(value)
            except OSError as rollback_error:
                logger.error(f"Could not restore {path}: {rollback_error}")
        return False
