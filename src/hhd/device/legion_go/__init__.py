import logging
from typing import Sequence

from hhd.plugins import (
    HHDPlugin,
)

from .slim import LegionGoSControllerPlugin
from .tablet import LegionGoControllersPlugin

logger = logging.getLogger(__name__)

LEGION_GO_CONFS = {
    "83E1": {
        "name": "Legion Go",
    },
    "83N0": {
        "name": "Legion Go 2",
    },
    "83N1": {
        "name": "Legion Go 2",
    },
}

# Original Go BIOS versions observed in hwinfo captures and debug logs.
LEGION_GO_BIOSES = {
    "N3CN26WW",
    "N3CN28WW",
    "N3CN29WW",
    "N3CN29WW_TDP02",
    "N3CN31WW",
    "N3CN35WW",
    "N3CN39WW",
    "N3CN40WW",
}

LEGION_S_CONFS = {
    "83L3": {
        "name": "Legion Go S Z2 Go",
    },
    "83N6": {
        "name": "Legion Go S Z1E",
    },
    "83Q2": {
        "name": "Legion Go S",
    },
    "83Q3": {
        "name": "Legion Go S",
    },
}


def _read_dmi(name: str) -> str | None:
    try:
        with open(f"/sys/devices/virtual/dmi/id/{name}") as f:
            return f.read().strip() or None
    except OSError:
        return None


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    dmi = _read_dmi("product_name")

    if dmi in LEGION_S_CONFS:
        return [LegionGoSControllerPlugin(dconf=LEGION_S_CONFS[dmi])]

    if dmi in LEGION_GO_CONFS:
        return [LegionGoControllersPlugin(dconf=LEGION_GO_CONFS[dmi])]

    # Some original Legion Go units have missing or invalid product names.
    vendor = _read_dmi("sys_vendor")
    bios = _read_dmi("bios_version")
    if (
        vendor and vendor.upper() == "LENOVO"
        and bios and bios.upper() in LEGION_GO_BIOSES
    ):
        logger.info(
            "Detected original Legion Go via BIOS fallback "
            "(vendor=%s, BIOS=%s, product=%s).",
            vendor,
            bios,
            dmi,
        )
        return [LegionGoControllersPlugin(dconf=LEGION_GO_CONFS["83E1"])]

    return []
