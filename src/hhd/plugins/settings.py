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

    type: Literal["button"]
    canonical: Sequence[str]
    id: str

    title: str
    hint: str
    default: bool | None


class BooleanSetting(TypedDict):
    """Checkbox container."""

    type: Literal["bool"]
    canonical: Sequence[str]
    id: str

    title: str
    hint: str
    default: bool | None


class MultipleSetting(TypedDict):
    """Select one container."""

    type: Literal["multiple"]
    canonical: Sequence[str]
    id: str

    title: str
    hint: str

    options: Sequence[str]
    default: str | None


class DiscreteSetting(TypedDict):
    """Ordered and fixed numerical options (etc. tdp)."""

    type: Literal["discrete"]
    canonical: Sequence[str]
    id: str

    title: str
    hint: str

    options: Sequence[int | float]
    default: int | float | None


class NumericalSetting(TypedDict):
    """Floating numerical option."""

    type: Literal["number"]
    canonical: Sequence[str]
    id: str

    title: str
    hint: str

    min: float | int | None
    max: float | int | None
    default: float | int | None


class ColorSetting(TypedDict):
    """RGB color setting."""

    type: Literal["color"]
    canonical: Sequence[str]
    id: str

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
    canonical: Sequence[str]
    id: str

    title: str
    hint: str

    children: Sequence[Setting | "Container" | "Mode"]


class Mode(TypedDict):
    """Holds a number of containers, only one of whih can be active at a time."""

    type: Literal["container"]
    canonical: Sequence[str]
    id: str

    title: str
    hint: str

    modes: Sequence[Container]
    default: str | None