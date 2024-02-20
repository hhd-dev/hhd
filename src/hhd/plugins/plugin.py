from typing import (
    Any,
    Literal,
    Mapping,
    NamedTuple,
    Protocol,
    Sequence,
    TypedDict,
)

from hhd.controller import Axis, Button, Configuration

from .conf import Config
from .settings import HHDSettings


class Context(NamedTuple):
    euid: int = 0
    egid: int = 0
    uid: int = 0
    gid: int = 0
    name: str = "root"
    # scratch: str = ""


class SettingsEvent(TypedDict):
    type: Literal["settings"]


class ProfileEvent(TypedDict):
    type: Literal["profile"]
    name: str
    config: Config | None


class ApplyEvent(TypedDict):
    type: Literal["apply"]
    name: str


class ConfigEvent(TypedDict):
    type: Literal["state"]
    config: Config


class InputEvent(TypedDict):
    type: Literal["input"]
    controller_id: int

    btn_state: Mapping[Button, bool]
    axis_state: Mapping[Axis, bool]
    conf_state: Mapping[Configuration, Any]


Event = ConfigEvent | InputEvent | ProfileEvent | ApplyEvent | SettingsEvent


class Emitter(Protocol):
    def __call__(self, event: Event | Sequence[Event]) -> None:
        pass


class HHDPlugin:
    name: str
    priority: int
    log: str

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        pass

    def settings(self) -> HHDSettings:
        return {}

    def validate(self, tags: Sequence[str], config: Any, value: Any):
        return False

    def prepare(self, conf: Config):
        pass

    def update(self, conf: Config):
        pass

    def close(self):
        pass


class HHDAutodetect(Protocol):
    def __call__(self, existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
        raise NotImplementedError()
