from collections.abc import Mapping
import logging
import pkg_resources
import sys

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


def main():
    handler = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        datefmt="%m-%d %H:%M",
        handlers=[handler],
    )
    handler.setFormatter(
        NewLineFormatter("%(asctime)s %(levelname)-8s |||%(message)s")
    )
    logger.info(RASTER)
    logger.info(f"Handheld Daemon starting...")

    # logger.info(sys.argv)
    plugins = {}
    for plugin in pkg_resources.iter_entry_points("hhd.plugins"):
        plugins[plugin.name] = plugin

    logger.info(f"Found plugins: {','.join(list(plugins))}")

    if len(sys.argv) <= 1:
        logger.error(f"No argument entered to select plugin, exitting...")
        return
    plugin = sys.argv[1]

    if plugin in plugins:
        logger.info(f"Launching plugin {plugin}")
        plugins[plugin].resolve()()
    else:
        logger.error(f"Plugin {plugin} not loaded.")

if __name__ == "__main__":
    main()
