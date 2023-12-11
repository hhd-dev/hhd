from typing import Any, Sequence

from hhd.plugins import HHDPluginV1, get_relative_fn
from .const import SUPPORTED_DEVICES


def run(**config: Any):
    from .base import power_button_run

    power_button_run(**config)


def autodetect():
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        prod = f.read().strip()

    for d in SUPPORTED_DEVICES:
        if d.prod_name == prod:
            return True

    return False


plugins: Sequence[HHDPluginV1] = [
    {
        "name": "powerbuttond",
        "autodetect": autodetect,
        "run": run,
        "config": None,
    }
]
