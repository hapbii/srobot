"""Robot coordinate contract shared by the server and its tests.

Sensor home is the folded web pose (0, 180, 0), never (0, 0, 0).
Changing physical ratios or home orientation requires recalibration.
"""
AXES = ('j1', 'j2', 'j3')
HOME_POSE = dict(zip(AXES, (0.0, 180.0, 0.0)))
GEAR_RATIO = dict.fromkeys(AXES, 20)
STEPS_PER_DEG = {a: 1600 * GEAR_RATIO[a] / 360 for a in AXES}
JOINT_LIMITS = {'j1': (-360, 360), 'j2': (-360, 360), 'j3': (-180, 180)}
MAX_SPEED = dict(zip(AXES, (2000, 2000, 1000)))
ACCEL = dict(zip(AXES, (3000, 3000, 1500)))
MIN_SPEED, SPEED_LIMIT = 120, 3000
ENCODER_TTL = 1.0
HOME_TIMEOUT = 190.0
PROTOCOL_VERSION = 2

def deg_to_steps(axis, deg):
    return round((deg - HOME_POSE[axis]) * STEPS_PER_DEG[axis])

def steps_to_deg(axis, steps):
    return HOME_POSE[axis] + steps / STEPS_PER_DEG[axis]
