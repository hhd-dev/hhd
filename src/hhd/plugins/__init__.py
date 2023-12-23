from .conf import Config
from .plugin import HHDAutodetect, HHDPlugin, HHDPluginInfo, Context, Emitter
from .settings import HHDSettings


def get_relative_fn(fn: str):
    """Returns the directory of a file relative to the script calling this function."""
    import inspect
    import os

    script_fn = inspect.currentframe().f_back.f_globals["__file__"]  # type: ignore
    dirname = os.path.dirname(script_fn)
    return os.path.join(dirname, fn)


__all__ = [
    "Config",
    "HHDSettings",
    "HHDAutodetect",
    "HHDPlugin",
    "HHDPluginInfo",
    "get_relative_fn",
    "Emitter",
    "Context",
]
