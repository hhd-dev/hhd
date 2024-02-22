import os
import logging

logger = logging.getLogger(__name__)

SENTINEL_FILE = os.environ.get("HHD_ADJ_SENTINEL", "/etc/adjustor_sentinel.lock")

def install_sentinel():
    try:
        with open(SENTINEL_FILE, 'w') as f:
            f.write('sentinel')
        return True
    except Exception as e:
        logger.warning(f"Could not create sentinel file at:\n{SENTINEL_FILE}\nwith error:\n{e}")
        return False
    
def remove_sentinel():
    try:
        os.remove(SENTINEL_FILE)
    except Exception as e:
        logger.warning(f"Could not remove sentinel file at:\n{SENTINEL_FILE}\nwith error:\n{e}")

def exists_sentinel():
    return os.path.isfile(SENTINEL_FILE)