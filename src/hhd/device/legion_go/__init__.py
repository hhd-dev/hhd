from typing import Sequence

from hhd.plugins import (
    HHDPlugin,
)

from .slim import LegionGoSControllerPlugin
from .tablet import LegionGoControllersPlugin

LEGION_GO_CONFS = {
    "83E1": {
        "name": "Legion Go",
    },
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


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()

    if dmi in LEGION_S_CONFS:
        return [LegionGoSControllerPlugin(dconf=LEGION_S_CONFS[dmi])]

    if dmi in LEGION_GO_CONFS:
        return [LegionGoControllersPlugin(dconf=LEGION_GO_CONFS[dmi])]

    return []
