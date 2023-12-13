import logging
import os


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


def setup_logger(log_dir: str | None = None, init: bool = True):
    from rich import get_console
    from rich.traceback import install
    from rich.logging import RichHandler
    from logging import handlers as lhandlers

    install()
    handlers = [RichHandler()]
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        handler = lhandlers.RotatingFileHandler(
            os.path.join(log_dir, "hhd.log"), maxBytes=10_000, backupCount=10
        )
        handler.setFormatter(
            NewLineFormatter("%(asctime)s %(module)-15s %(levelname)-8s|||%(message)s")
        )

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
