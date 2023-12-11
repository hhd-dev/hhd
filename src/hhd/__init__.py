import logging


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


def setup_logger():
    handler = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        datefmt="%m-%d %H:%M",
        handlers=[handler],
    )
    handler.setFormatter(NewLineFormatter("%(asctime)s %(levelname)-8s |||%(message)s"))
    logger.info(RASTER)
    logger.info(f"Handheld Daemon starting...")
