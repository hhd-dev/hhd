import sys

from .core import fan_pwm_tester

if __name__ == "__main__":
    observe_only = "--observe" in sys.argv
    fan_pwm_tester(observe_only=observe_only)