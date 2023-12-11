from typing import Any, Sequence

from hhd.plugins import HHDPluginV1, get_relative_fn


def run(**config: Any):
    from .base import power_button_run

    power_button_run(**config)


def autodetect():
    # Limit to legion go for now, as its the only device
    # Supported by hhd
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        return f.read().strip() == "83E1"


plugins: Sequence[HHDPluginV1] = [
    {
        "name": "powerbuttond",
        "autodetect": autodetect,
        "run": run,
        "config": None,
    }
]
