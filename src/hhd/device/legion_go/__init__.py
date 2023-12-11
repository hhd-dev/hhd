from typing import Any, Sequence

from hhd.plugins import HHDPluginV1, get_relative_fn


def controllers_run(**config: Any):
    from .base import plugin_run

    plugin_run(**config)


def controllers_autodetect():
    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        return f.read().strip() == "83E1"


plugins: Sequence[HHDPluginV1] = [
    {
        "name": "legion_go_controllers",
        "autodetect": controllers_autodetect,
        "run": controllers_run,
        "config": get_relative_fn("config.yaml"),
        "config_version": 2,
    }
]


def main():
    from .base import main

    main(False)


if __name__ == "__main__":
    main()
