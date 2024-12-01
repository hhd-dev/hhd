# The objective of this fan algorithm is simple: receive a fan curve for a specific
# power profile, the current system temperature, and the current fan speed.
# Then, have a single variable memory: the current acceleration.
# At each point, use a derived jerk to modify the acceleration and move the
# speed to the desired point smoothly.

# Maximum typical transition span of the fan speed (e.g., from 20% to 70%)
# This transition span should take exactly the seconds specified below
# E.g., if the fan begins to move from 20% to 70% with 0 acceleration, where
# the temperature is at 70C, it should take at most 5 seconds.
SPEED_SPAN = 0.5

# The ratio of the curve to begin decelerating the fan change rpm/s^2
# E.g., when going from 20% to 70%, the fan should begin decelerating
# at 0.7*(70-20) + 20 = 62% speed.
DECEL_RATIO = 0.5

# The temperature at which the fan should use the high accel speed.
HIGH_TEMP_EDGE = 65
HIGH_TEMP_JUNCTION = 75

# Allow for a gradual transition if the temperature is low
# Speed up if not.
ACCEL_UP_LOWT_T = 30
ACCEL_UP_HIGH_T = 20
# Penalize going down to avoid dithering
ACCEL_DOWN_T = 40

JERK_TOLERANCE = 0.9
MAX_ACCEL = 0.4
SETPOINT_DEVIATION = 0.01

UPDATE_FREQUENCY = 5
UPDATE_T = 1 / UPDATE_FREQUENCY
SETPOINT_UPDATE_FREQUENCY = 1
SETPOINT_UPDATE_T = 1 / SETPOINT_UPDATE_FREQUENCY


def _calculate_jerk(speed_span, decel_ratio, freq, time):
    """Calculate the required positive and negative jerks such that the
    fan can cross the speed span (e.g., 50%) in the specified time (e.g., 5s)
    given an update frequency (e.g., 3), and the point at which it should start
    decelerating (e.g., 0.3).
    """

    jerk_accel = (2 * speed_span) / ((time * freq) ** 2) / ((1 - decel_ratio) ** 2)
    jerk_decel = -(1 - decel_ratio) / decel_ratio * jerk_accel
    return jerk_accel, jerk_decel


def calculate_jerk(t_target: float, increase: bool, junction: bool):
    """Calculate the jerk based on the target temperature and whether the fan
    speed should increase or decrease to reach it.

    Allow for specifying whether the temperature probe is in the junction or the
    edge, as junction reaches thermal saturation faster and at higher temperatures."""
    if not increase:
        return _calculate_jerk(SPEED_SPAN, DECEL_RATIO, UPDATE_FREQUENCY, ACCEL_DOWN_T)

    if (junction and t_target > HIGH_TEMP_JUNCTION) or (
        not junction and t_target > HIGH_TEMP_EDGE
    ):
        return _calculate_jerk(
            SPEED_SPAN, DECEL_RATIO, UPDATE_FREQUENCY, ACCEL_UP_HIGH_T
        )

    return _calculate_jerk(SPEED_SPAN, DECEL_RATIO, UPDATE_FREQUENCY, ACCEL_UP_LOWT_T)


def move_to_setpoint(v_curr, a_curr, jerk_accel, jerk_decel, v_target):
    """Update the current fan speed and acceleration by either using jerk_accel
    which will increase acceleration to meet the target speed or jerk_decel
    which will begin to decrease it to 0.

    The choice between jerk_accel and jerk_decel is made by calculating the
    minimum negative jerk required to decelerate to a=0 when reaching the target.
    If the minimum jerk is smaller than jerk_decel, we use jerk_accel.
    To avoid overshoots, a tolerance is used to start decelerating a bit earlier
    than when the minimum jerk reaches the value of jerk_decel.
    """

    # Flip the jerks if the target is lower than the current speed
    diff = v_target - v_curr
    if diff < 0:
        jerk_accel = -jerk_accel
        jerk_decel = -jerk_decel

    correct_direction = (diff > 0 and a_curr > 0) or (diff < 0 and a_curr < 0)
    non_zero = abs(diff) > 1e-3

    # Always accelerate if we are on the right direction or speed is zero
    # Start decelerating once we run out of opposite jerk.
    accel = True
    if correct_direction and non_zero:
        min_jerk_neg = -(a_curr**2) / 2 / diff
        accel = abs(min_jerk_neg) < JERK_TOLERANCE * abs(jerk_decel)

    if accel:
        jerk = jerk_accel
    else:
        jerk = jerk_decel

    # Calculate the new acceleration
    a_new = a_curr + jerk
    v_new = v_curr + a_new
    return v_new, a_new


def sanitize_fan_values(v: float, a: float):
    return max(0, min(1, v)), max(-MAX_ACCEL, min(MAX_ACCEL, a))


def has_reached_setpoint(v_curr, a_curr, v_target):
    """Check if the current fan speed has reached the target speed.

    If true, lower the update rate and set a_curr to 0 to avoid dithering.
    """
    return abs(v_curr - v_target) < SETPOINT_DEVIATION


def update_setpoint(temp: float, curr: int, fan_curve: dict[int, float]):
    """Update the setpoint given the current temperature, fan curve, and previous setpoint.

    Fan curve is a dictionary of increasing temperatures to fan speeds.
    """

    targets = list(fan_curve.keys())
    assert curr in targets, "Current setpoint not in fan curve"

    idx = targets.index(curr)

    # Add some hysterisis to avoid dithering
    if idx > 0:
        prev = targets[idx - 1]
        if temp < prev:
            return prev

    if idx < len(targets) - 1:
        next = targets[idx + 1]
        if temp > next:
            return next

    return curr


def get_initial_setpoint(temp: float, fan_curve: dict[int, float]):
    """Get the initial setpoint given the current temperature and fan curve.

    Fan curve is a dictionary of increasing temperatures to fan speeds.
    """

    targets = list(fan_curve.keys())
    for idx, target in enumerate(targets):
        if temp < target:
            return targets[idx - 1] if idx else targets[0]
    return targets[-1]
