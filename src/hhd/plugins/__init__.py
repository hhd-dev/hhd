from typing import Any, Protocol, TypedDict


def get_relative_fn(fn: str):
    """Returns the directory of a file relative to the script calling this function."""
    import inspect
    import os

    script_fn = inspect.currentframe().f_back.f_globals["__file__"]  # type: ignore
    dirname = os.path.dirname(script_fn)
    return os.path.join(dirname, fn)


class HHDPluginV1Autodetect(Protocol):
    def __call__(self) -> bool:
        return True


class HHDPluginV1Run(Protocol):
    def __call__(self, **config: Any) -> None:
        pass


class HHDPluginV1Nonversioned(TypedDict):
    name: str
    autodetect: HHDPluginV1Autodetect
    run: HHDPluginV1Run
    config: str | None


class HHDPluginV1Versioned(TypedDict):
    name: str
    autodetect: HHDPluginV1Autodetect
    run: HHDPluginV1Run
    config: str | None
    config_version: int


HHDPluginV1 = HHDPluginV1Nonversioned | HHDPluginV1Versioned
"""Initial version of HHD plugins. These plugins use static configuration,
and it is not possible for them to share configuration with each other
of communicate through d-bus. Restarting hhd is required for reloading
configuration.

The plugins specify a name, a run function, and the location of a template
config file. Use the function `get_relative_fn()` to retrieve the directory
of the script executing it, and place the config file relative to it.

To stop the plugin, a KeyboardInterrupt is raised.

Provide `config_version` to replace your config file on startup when a version
changes.

@warning: `run()` needs to be a global function, e.g., it can not
be a lambda and decorators are tricky."""
