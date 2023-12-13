import logging
import os
from logging import LogRecord
from logging.handlers import RotatingFileHandler

from .utils import Perms, expanduser, restore_priviledge, switch_priviledge

logger = logging.getLogger(__name__)

RASTER = """\
   _______   _______    ______  
  /    /  ╲╲/    /  ╲╲_/      ╲╲
 /        //        //        //
/         /         /         / 
╲___/____/╲___/____/╲________/  \n"""


class NewLineFormatter(logging.Formatter):
    """Aligns newlines during multiline prints."""

    def format(self, record):
        msg = super().format(record)
        if (idx := msg.index("|||")) != -1:
            preamble = msg[:idx]
            msg = msg.replace("|||", "").replace("\n", "\n" + (" " * len(preamble)))
        return msg


class UserRotatingFileHandler(RotatingFileHandler):
    def __init__(
        self,
        filename: str,
        mode: str = "a",
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
        perms: Perms | None = None,
    ) -> None:
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay, errors)
        self.perms = perms

    def emit(self, record: LogRecord) -> None:
        try:
            # Set permissions to log as user
            if self.perms:
                old = switch_priviledge(self.perms, False)
            else:
                old = None
            RotatingFileHandler.emit(self, record)
            if old:
                restore_priviledge(old)
        except Exception:
            self.handleError(record)


def setup_logger(
    log_dir: str | None = None, init: bool = True, perms: Perms | None = None
):
    from rich import get_console
    from rich.logging import RichHandler
    from rich.traceback import install

    if log_dir:
        log_dir = expanduser(log_dir, perms)

    install()
    handlers = []
    handlers.append(RichHandler())
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        handler = UserRotatingFileHandler(
            os.path.join(log_dir, "hhd.log"),
            maxBytes=10_000_000,
            backupCount=10,
            perms=perms,
        )
        handler.setFormatter(
            NewLineFormatter("%(asctime)s %(module)-15s %(levelname)-8s|||%(message)s")
        )
        handler.doRollover()
        handlers.append(handler)

    FORMAT = "%(message)s"
    logging.basicConfig(
        level=logging.INFO,
        datefmt="[%d/%m %H:%M]",
        format=FORMAT,
        handlers=handlers,
    )
    if init:
        get_console().print(RASTER, justify="full", markup=False, highlight=False)
        logger.info(f"Handheld Daemon starting...")
