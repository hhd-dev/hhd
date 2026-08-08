__all__ = ["HHDHTTPServer"]


def __getattr__(name: str):
    if name == "HHDHTTPServer":
        from .api import HHDHTTPServer

        globals()[name] = HHDHTTPServer
        return HHDHTTPServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
