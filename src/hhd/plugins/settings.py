from functools import reduce
from typing import (
    Literal,
    Mapping,
    MutableMapping,
    Sequence,
    TypedDict,
    cast,
)

#
# UI settings
#


class ButtonSetting(TypedDict):
    """Just a button, emits an event. Used for resets, etc."""

    type: Literal["event"]
    family: Sequence[str]
    title: str
    hint: str
    persistent: bool

    default: bool | None


class BooleanSetting(TypedDict):
    """Checkbox container."""

    type: Literal["bool"]
    family: Sequence[str]
    title: str
    hint: str
    persistent: bool

    default: bool | None


class MultipleSetting(TypedDict):
    """Select one container."""

    type: Literal["multiple"]
    family: Sequence[str]
    title: str
    hint: str
    persistent: bool

    options: Sequence[str]
    default: str | None


class DiscreteSetting(TypedDict):
    """Ordered and fixed numerical options (etc. tdp)."""

    type: Literal["discrete"]
    family: Sequence[str]
    title: str
    hint: str
    persistent: bool

    options: Sequence[int | float]
    default: int | float | None


class NumericalSetting(TypedDict):
    """Floating numerical option."""

    type: Literal["number"]
    family: Sequence[str]
    title: str
    hint: str
    persistent: bool

    min: float | int | None
    max: float | int | None
    default: float | int | None


class ColorSetting(TypedDict):
    """RGB color setting."""

    type: Literal["color"]
    family: Sequence[str]
    title: str
    hint: str
    persistent: bool


Setting = (
    ButtonSetting
    | BooleanSetting
    | MultipleSetting
    | DiscreteSetting
    | NumericalSetting
    | ColorSetting
)

#
# Containers for settings
#


class Container(TypedDict):
    """Holds a variety of settings."""

    type: Literal["container"]
    family: Sequence[str]
    title: str
    hint: str

    children: MutableMapping[str, "Setting | Container | Mode"]


class Mode(TypedDict):
    """Holds a number of containers, only one of whih can be active at a time."""

    type: Literal["mode"]
    family: Sequence[str]
    title: str
    hint: str
    persistent: bool

    modes: MutableMapping[str, Container]
    default: str | None


Section = MutableMapping[str, Container]

HHDSettings = Mapping[str, Section]


def parse(d: Setting | Container | Mode, prev: Sequence[str], out: MutableMapping):
    new_prev = list(prev)
    match d["type"]:
        case "container":
            for k, v in d["children"].items():
                parse(v, new_prev + [k], out)
        case "mode":
            out[".".join(new_prev) + ".mode"] = d.get("default", None)

            for k, v in d["modes"].items():
                parse(v, new_prev + [k], out)
        case other:
            out[".".join(new_prev)] = d.get("default", None)


def parse_settings(sets: HHDSettings):
    out = {}
    for name, sec in sets.items():
        for cname, cont in sec.items():
            parse(cont, [name, cname], out)
    return out


def merge_reduce(
    a: Setting | Container | Mode, b: Setting | Container | Mode
) -> Setting | Container | Mode:
    if a["type"] != b["type"]:
        return b

    match a["type"]:
        case "container":
            out = cast(Container, dict(b))
            new_children = dict(a["children"])
            for k, v in b.items():
                if k in out:
                    out[k] = merge_reduce(out[k], b[k])
                else:
                    out[k] = v
            out["children"] = new_children
            return out
        case "mode":
            out = cast(Mode, dict(b))
            new_children = dict(a["modes"])
            for k, v in b.items():
                if k in out:
                    out[k] = merge_reduce(out[k], b[k])
                else:
                    out[k] = v
            out["modes"] = new_children
            return out
        case _:
            return b


def merge_reduce_sec(a: Section, b: Section):
    out = dict(a)
    for k, v in b.items():
        if k in out:
            out[k] = cast(Container, merge_reduce(out[k], b[k]))
        else:
            out[k] = v

    return out


def merge_reduce_secs(a: HHDSettings, b: HHDSettings):
    out = dict(a)
    for k, v in b.items():
        if k in out:
            out[k] = merge_reduce_sec(out[k], b[k])
        else:
            out[k] = v

    return out


def merge_settings(sets: Sequence[HHDSettings]):
    return reduce(merge_reduce_secs, sets)
