from hhd.plugins import HHDLocale, get_relative_fn


def _(arg: str):
    return arg


def locales() -> list[HHDLocale]:
    return [
        {"dir": get_relative_fn("./"), "domain": "hhd", "priority": 10},
        {"dir": get_relative_fn("./"), "domain": "adjustor", "priority": 20},
    ]
