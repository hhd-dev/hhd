import logging
import sys
from collections.abc import Mapping

import pkg_resources

from hhd import setup_logger

logger = logging.getLogger(__name__)


def main():
    setup_logger()
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
