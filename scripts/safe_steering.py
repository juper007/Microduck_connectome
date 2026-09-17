"""Pure simulation-only yaw decoder. Caller must tick independently at 50 Hz."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Readout:
    timestamp_ns: int
    sequence: int
    left: float
    right: float
    healthy: bool = True


class SteeringGate:
    """Inputs are mean 100 ms spike counts divided by five (range 0..1).

    Stale/invalid/stop paths bypass slew limiting and immediately return zero.
    This class has no IPC and does not itself provide a process-crash watchdog.
    """
    def __init__(self, yaw_sign):
        if type(yaw_sign) is not int or yaw_sign not in (-1, 1):
            raise ValueError('A measured yaw_sign is required')
        self.sign = yaw_sign
        self.yaw = 0.0
        self.previous_ns = None
        self.sequence = -1
        self.last_sample = None

    def tick(self, sample, now_ns, emergency=False):
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError('now_ns must be nonnegative monotonic nanoseconds')
        dt = 0.0 if self.previous_ns is None else min(0.02, max(0.0, (now_ns-self.previous_ns)/1e9))
        clock_ok = self.previous_ns is None or now_ns > self.previous_ns
        self.previous_ns = now_ns
        valid = (isinstance(sample, Readout) and type(sample.timestamp_ns) is int
                 and type(sample.sequence) is int and sample.sequence >= self.sequence
                 and sample.sequence >= 0 and sample.healthy is True
                 and 0 <= now_ns-sample.timestamp_ns < 100_000_000)
        if valid:
            valid = all(type(v) in (int,float) and math.isfinite(v) and 0 <= v <= 1
                        for v in (sample.left,sample.right))
        if valid and sample.sequence == self.sequence and sample != self.last_sample:
            valid = False
        if emergency or not clock_ok or not valid:
            self.yaw = 0.0
            return {'vx':0.0,'vy':0.0,'vyaw':0.0,'stop':True,'timestamp_ns':now_ns,
                    'sequence':max(0,self.sequence),'confidence':0.0,'source':'male-cns-controller'}
        self.sequence = sample.sequence
        self.last_sample = sample
        target = self.sign * 0.5 * (sample.left-sample.right)
        self.yaw += max(-1.5*dt, min(1.5*dt,target-self.yaw))
        self.yaw = max(-0.5,min(0.5,self.yaw))
        return {'vx':0.0,'vy':0.0,'vyaw':self.yaw,'stop':False,'timestamp_ns':now_ns,
                'sequence':self.sequence,'confidence':1.0,'source':'male-cns-controller'}
