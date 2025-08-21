import logging
import time
from typing import TypedDict
from threading import Lock, Event

from .alg import (
    SETPOINT_UPDATE_T,
    UPDATE_T,
    calculate_jerk,
    get_initial_setpoint,
    has_reached_setpoint,
    move_to_setpoint,
    sanitize_fan_values,
    update_setpoint,
)
from .utils import (
    find_edge_temp,
    find_fans,
    find_tctl_temp,
    read_fan_speed,
    read_temp,
    write_fan_speed,
)

logger = logging.getLogger(__name__)


class FanInfo(TypedDict):
    tctl: str
    edge: str
    fans: list[str]


class FanData(TypedDict):
    a: float
    v: float
    t_target: int


class FanState(TypedDict):
    v_curr: float
    v_target: float
    v_target_pwm: int
    t_target: int
    v_rpm: list[int]
    t_junction: float
    t_edge: float
    fan_data: FanData
    in_setpoint: bool


def get_fan_info() -> FanInfo | None:
    tctl = find_tctl_temp()
    if tctl is None:
        logger.error("Could not find tctl junction temperature.")
        return None

    edge = find_edge_temp()
    if edge is None:
        logger.error("Could not find edge temperature.")
        return None

    fans = find_fans()
    if not fans:
        logger.error("Could not find PWM controllable fans.")
        return None

    return {"tctl": tctl, "edge": edge, "fans": fans}


def calculate_fan_speed(
    temp: float, data: FanData | None, fan_curve: dict[int, float], junction: bool
) -> tuple[float, bool, FanData]:
    if data is None:
        # Initialize with best guess
        t_target = get_initial_setpoint(temp, fan_curve)
        v_curr = fan_curve[t_target]
        a_curr = 0
        return v_curr, False, {"a": a_curr, "v": v_curr, "t_target": t_target}

    # Get values and new temp target setpoint
    v_curr = data["v"]
    a_curr = data["a"]
    t_target = data["t_target"]
    t_target = update_setpoint(temp, t_target, fan_curve)

    # Pin values if we are in the setpoint
    if has_reached_setpoint(v_curr, a_curr, fan_curve[t_target]):
        a_curr = 0
        v_curr = fan_curve[t_target]
        return v_curr, True, {"a": a_curr, "v": v_curr, "t_target": t_target}

    v_target = fan_curve[t_target]
    jerk_accel, jerk_decel = calculate_jerk(t_target, v_target > v_curr, junction)
    v_new, a_new = move_to_setpoint(v_curr, a_curr, jerk_accel, jerk_decel, v_target)
    v_new, a_new = sanitize_fan_values(v_new, a_new)

    return v_new, False, {"a": a_new, "v": v_new, "t_target": t_target}


def set_fans_to_pwm(enable: bool, fan_info: FanInfo):
    for _, fn_enable, _, legacy in fan_info["fans"]:
        with open(fn_enable, "w") as f:
            if enable:
                f.write("1")
            else:
                f.write("0" if legacy else "2")


def update_fan_speed(
    state: FanState | None,
    fan_info: FanInfo,
    fan_curve: dict[int, float],
    junction: bool,
    observe_only: bool = False,
) -> tuple[bool, FanState]:
    t_edge = read_temp(fan_info["edge"])
    t_junction = read_temp(fan_info["tctl"])

    t_curr = t_junction if junction else t_edge
    data = state["fan_data"] if state else None
    v_curr, in_setpoint, data = calculate_fan_speed(t_curr, data, fan_curve, junction)

    v_curr_int = min(255, max(0, int(v_curr * 255)))
    if not observe_only:
        if state is None or state["v_target_pwm"] != v_curr_int:
            for v_fn, _, _, _ in fan_info["fans"]:
                write_fan_speed(v_fn, v_curr_int)

    fan_speeds = [read_fan_speed(rpm_fn) for _, _, rpm_fn, _ in fan_info["fans"] if rpm_fn]
    return (
        in_setpoint,
        {
            "v_curr": v_curr,
            "v_target": fan_curve[data["t_target"]],
            "v_target_pwm": v_curr_int,
            "v_rpm": fan_speeds,
            "t_junction": t_junction,
            "t_edge": t_edge,
            "t_target": data["t_target"],
            "fan_data": data,
            "in_setpoint": in_setpoint,
        },
    )


def fan_worker(
    info: FanInfo,
    should_exit: Event,
    lock: Lock,
    fan_curve: dict[int, float],
    state: FanState,
    junction: Event,
):
    try:
        set_fans_to_pwm(True, info)
        while not should_exit.is_set():
            with lock:
                state_tmp = state or None  # First time state will be empty
                in_setpoint, state_tmp = update_fan_speed(
                    state_tmp, info, fan_curve, junction.is_set()
                )
                state.update(state_tmp)
            time.sleep(SETPOINT_UPDATE_T if in_setpoint else UPDATE_T)
    except Exception as e:
        logger.error(f"Fan worker failed:\n{e}")
    finally:
        set_fans_to_pwm(False, info)


def fan_pwm_tester(normal_curve: bool = True, observe_only: bool = False):
    fan_info = get_fan_info()
    if fan_info is None:
        return

    if normal_curve:
        fan_curve = {
            50: 0.3,
            60: 0.35,
            70: 0.4,
            80: 0.5,
            85: 0.6,
            90: 0.8,
            100: 0.9,
        }
        fan_curve = {
            40: 0.2,
            45: 0.3,
            50: 0.4,
            55: 0.45,
            60: 0.55,
            65: 0.7,
            70: 0.8,
            80: 0.85,
            90: 0.9,
            100: 1,
        }
    else:
        fan_curve = {
            50: 0.3,
            60: 0.3,
            65: 0.9,
            80: 0.9,
            90: 0.9,
            100: 1,
        }

    try:
        if not observe_only:
            set_fans_to_pwm(True, fan_info)

        MAX_FAN = 5300

        state = None
        for i in range(10000000):
            in_setpoint, state = update_fan_speed(
                state, fan_info, fan_curve, False, observe_only=observe_only
            )

            print(
                f"\n> {i:05d}: {'in setpoint' if in_setpoint else 'updating'}{' (observe)' if observe_only else ''}"
            )
            print(
                f"  Junction: {state['t_junction']:.2f}C, Edge: {state['t_edge']:.2f}C"
            )
            print(
                f"  Current: {state['v_curr']*100:.1f}%, Target: {state['v_target']*100:.1f}%"
            )
            print(
                f"  Fan speeds: {' '.join(map(lambda rpm: f"{rpm:4d}rpm/{MAX_FAN}rpm ({100*rpm/MAX_FAN:.1f}%)", state['v_rpm']))}"
            )
            time.sleep(SETPOINT_UPDATE_T if in_setpoint else UPDATE_T)
    except KeyboardInterrupt:
        print("Exiting fan test.")
    finally:
        set_fans_to_pwm(False, fan_info)
