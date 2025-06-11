def get_relative_fn(fn: str):
    """Returns the directory of a file relative to the script calling this function."""
    import inspect
    import os

    script_fn = inspect.currentframe().f_back.f_globals["__file__"]  # type: ignore
    dirname = os.path.dirname(script_fn)
    return os.path.join(dirname, fn)


def load_relative_yaml(fn: str):
    """Returns the yaml data of a file in the relative dir provided."""
    import inspect
    import os
    import yaml

    script_fn = inspect.currentframe().f_back.f_globals["__file__"]  # type: ignore
    dirname = os.path.dirname(script_fn)
    with open(os.path.join(dirname, fn), "r") as f:
        return yaml.safe_load(f)
