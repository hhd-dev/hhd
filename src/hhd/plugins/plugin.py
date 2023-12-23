from typing import (Any, Literal, Mapping, MutableMapping, MutableSequence,
                    NamedTuple, Protocol, Sequence, TypedDict)

from hhd.controller import Axis, Button, Configuration
from hhd.controller import Event as ControllerEvent

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


class ConfigEvent(TypedDict):
    type: Literal["config"]
    config: Config


class InputEvent(TypedDict):
    type: Literal["input"]
    controller_id: int

    btn_state: Mapping[Button, bool]
    axis_state: Mapping[Axis, bool]
    conf_state: Mapping[Configuration, Any]

    events: Sequence[ControllerEvent]


Event = ConfigEvent | InputEvent


class Emitter(Protocol):
    def __call__(self, event: Event | Sequence[Event]) -> None:
        pass


class HHDPlugin:
    def open(
        self,
        conf: Config,
        emit: Emitter,
        context: Context,
    ):
        pass

    def settings(self) -> HHDSettings:
        return {}

    def prepare(self, state: Config):
        pass

    def update(self, state: Config):
        pass

    def close(self):
        pass


class HHDPluginNonversioned(TypedDict):
    name: str
    plugin: HHDPlugin
    priority: int


class HHDPluginersioned(TypedDict):
    name: str
    plugin: HHDPlugin
    priority: int
    config: str
    version: int


HHDPluginInfo = HHDPluginNonversioned | HHDPluginersioned


class HHDAutodetect(Protocol):
    def __call__(self, existing: Sequence[HHDPlugin]) -> Sequence[HHDPluginInfo]:
        raise NotImplementedError()
