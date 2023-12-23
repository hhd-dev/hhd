from typing import (
    MutableMapping,
    MutableSequence,
    TypedDict,
    Literal,
    Mapping,
    Sequence,
    Any,
    Protocol,
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

    default: bool | None


class BooleanSetting(TypedDict):
    """Checkbox container."""

    type: Literal["bool"]
    family: Sequence[str]
    title: str
    hint: str

    default: bool | None


class MultipleSetting(TypedDict):
    """Select one container."""

    type: Literal["multiple"]
    family: Sequence[str]
    title: str
    hint: str

    options: Sequence[str]
    default: str | None


class DiscreteSetting(TypedDict):
    """Ordered and fixed numerical options (etc. tdp)."""

    type: Literal["discrete"]
    family: Sequence[str]
    title: str
    hint: str

    options: Sequence[int | float]
    default: int | float | None


class NumericalSetting(TypedDict):
    """Floating numerical option."""

    type: Literal["number"]
    family: Sequence[str]
    title: str
    hint: str

    min: float | int | None
    max: float | int | None
    default: float | int | None


class ColorSetting(TypedDict):
    """RGB color setting."""

    type: Literal["color"]
    family: Sequence[str]
    title: str
    hint: str

    red: int
    green: int
    blue: int


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

    children: MutableMapping[str, Setting | "Container" | "Mode"]


class Mode(TypedDict):
    """Holds a number of containers, only one of whih can be active at a time."""

    type: Literal["mode"]
    family: Sequence[str]
    title: str
    hint: str

    modes: MutableMapping[str, Container]
    default: str | None


Section = Container

HHDSettings = Mapping[str, Section]


def parse(d: Setting | "Container" | "Mode", prev: Sequence[str], out: MutableMapping):
    new_prev = list(prev)
    match d["type"]:
        case "container":
            for k, v in d["children"].items():
                parse(v, new_prev + [k], out)
        case "mode":
            out[".".join(new_prev)] = "mode"
            for k, v in d["modes"].items():
                parse(v, new_prev + [k], out)
        case other:
            out[".".join(new_prev)] = other


def parse_settings(sets: HHDSettings):
    out = {}
    for name, sec in sets.items():
        parse(sec, [name], out)
    return out
