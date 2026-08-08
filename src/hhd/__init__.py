__all__ = ["setup_logger", "RASTER"]


def __getattr__(name: str):
    if name in __all__:
        from .logging import RASTER, setup_logger

        globals().update(RASTER=RASTER, setup_logger=setup_logger)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
