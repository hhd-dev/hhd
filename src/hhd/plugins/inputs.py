from .utils import load_relative_yaml


def get_touchpad_config():
    return load_relative_yaml("touchpad.yml")
