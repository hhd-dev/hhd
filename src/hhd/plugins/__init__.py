from .initial import get_relative_fn, HHDPluginV1

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

from hhd.controller import Axis, Button, Configuration, Event as ControllerEvent

from .conf import Config


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
    def __call__(self, event: Event | Sequence[Event]) -> Any:
        pass


class HHDPlugin:
    def open(self, conf: Config, emitter: Emitter):
        pass

    def prepare(self, state: Config):
        pass

    def update(self, state: Config):
        pass

    def close(self):
        pass
