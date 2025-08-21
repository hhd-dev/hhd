import logging

logger = logging.getLogger(__name__)


def get_platform_choices():
    try:
        with open("/sys/firmware/acpi/platform_profile_choices", "r") as f:
            return f.read().strip().split(" ")
    except Exception:
        logger.info(
            f"Could not enumerate platform profile choices. Disabling platform profile."
        )
        return None


def set_platform_profile(prof: str):
    try:
        logger.info(f"Setting platform profile to '{prof}'")
        with open("/sys/firmware/acpi/platform_profile", "w") as f:
            f.write(prof)
        return True
    except Exception as e:
        logger.error(f"Could not set platform profile with error:\n{e}")
        return False


def get_platform_profile():
    try:
        with open("/sys/firmware/acpi/platform_profile", "r") as f:
            return f.read().replace("\n", "")
    except Exception as e:
        logger.error(f"Could not read platform profile with error:\n{e}")
        return None
