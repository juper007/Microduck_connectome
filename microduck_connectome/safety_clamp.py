"""Independent Phase-5 internal safety envelope."""

from collections.abc import Mapping
from dataclasses import dataclass
import json, math
from pathlib import Path

from .control_contracts import ControlContractError, make_behavior_intent, validate_behavior_intent


class SafetyClampError(ValueError):
    pass


@dataclass(frozen=True)
class SafetyEnvelope:
    max_abs_vx_mps: float = 0.08
    max_abs_vy_mps: float = 0.0
    max_abs_vyaw_radps: float = 0.50
    max_delta_vx_per_s: float = 0.20
    max_delta_vyaw_per_s2: float = 1.50

    def __post_init__(self):
        values=(self.max_abs_vx_mps,self.max_abs_vy_mps,self.max_abs_vyaw_radps,
                self.max_delta_vx_per_s,self.max_delta_vyaw_per_s2)
        expected=(0.08,0.0,0.50,0.20,1.50)
        for value,target in zip(values,expected):
            if isinstance(value,bool) or not isinstance(value,(int,float)):
                raise SafetyClampError("envelope values must be numeric")
            if not math.isfinite(float(value)) or float(value)!=target:
                raise SafetyClampError("envelope must match frozen limits")


def load_safety_envelope(path):
    try:
        value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as error:
        raise SafetyClampError("cannot load safety envelope") from error
    fields={"schema_version","max_abs_vx_mps","max_abs_vy_mps","max_abs_vyaw_radps",
            "max_delta_vx_per_s","max_delta_vyaw_per_s2","source","scope"}
    if not isinstance(value,Mapping) or set(value)!=fields:
        raise SafetyClampError("config fields mismatch")
    if value["schema_version"]!="safety-envelope-v1" or value["source"]!="male-cns-controller":
        raise SafetyClampError("config schema/source mismatch")
    return SafetyEnvelope(value["max_abs_vx_mps"],value["max_abs_vy_mps"],
        value["max_abs_vyaw_radps"],value["max_delta_vx_per_s"],value["max_delta_vyaw_per_s2"])


class SafetyClamp:
    def __init__(self,envelope=None):
        self.envelope=envelope or SafetyEnvelope()
        if not isinstance(self.envelope,SafetyEnvelope):
            raise SafetyClampError("envelope must be SafetyEnvelope")
        self.reset()

    def reset(self):
        self._previous=None

    @staticmethod
    def _bounded(value,limit):
        return max(-limit,min(limit,value))

    @staticmethod
    def _slew(value,previous,delta):
        return max(previous-delta,min(previous+delta,value))

    def _metadata(self,now_ns,sequence):
        if type(now_ns) is not int or now_ns<0:
            raise SafetyClampError("now_ns must be non-negative int")
        if type(sequence) is not int or sequence<0:
            raise SafetyClampError("fallback_sequence must be non-negative int")

    def _neutralize(self,now_ns,sequence,reason):
        safe=make_behavior_intent(timestamp_ns=now_ns,sequence=sequence,
                                  vx=0.0,vy=0.0,vyaw=0.0,stop=True,confidence=0.0)
        self._previous=safe
        return {"intent":safe,"clamp_applied":True,"reasons":[reason]}

    def apply(self,intent,*,now_ns,fallback_sequence):
        self._metadata(now_ns,fallback_sequence)
        try:
            value=validate_behavior_intent(intent)
        except ControlContractError:
            return self._neutralize(now_ns,fallback_sequence,"invalid_intent")
        if value["timestamp_ns"]>now_ns:
            return self._neutralize(now_ns,fallback_sequence,"future_timestamp")

        prev=self._previous
        if prev is not None:
            if value["timestamp_ns"]<=prev["timestamp_ns"]:
                return self._neutralize(now_ns,fallback_sequence,"nonmonotonic_timestamp")
            if value["sequence"]<=prev["sequence"]:
                return self._neutralize(now_ns,fallback_sequence,"nonmonotonic_sequence")

        if value["stop"]:
            safe=make_behavior_intent(timestamp_ns=value["timestamp_ns"],sequence=value["sequence"],
                                      stop=True,confidence=value["confidence"])
            self._previous=safe
            return {"intent":safe,"clamp_applied":True,"reasons":["stop_override"]}

        reasons=[]
        vx=self._bounded(value["vx"],0.08)
        if vx!=value["vx"]: reasons.append("vx_magnitude")
        vy=0.0
        if value["vy"]!=0.0: reasons.append("vy_forced_zero")
        yaw=self._bounded(value["vyaw"],0.50)
        if yaw!=value["vyaw"]: reasons.append("vyaw_magnitude")

        if prev is not None:
            dt=(value["timestamp_ns"]-prev["timestamp_ns"])/1e9
            limited=self._slew(vx,prev["vx"],0.20*dt)
            if limited!=vx: reasons.append("vx_slew")
            vx=limited
            limited=self._slew(yaw,prev["vyaw"],1.50*dt)
            if limited!=yaw: reasons.append("vyaw_slew")
            yaw=limited

        safe=make_behavior_intent(timestamp_ns=value["timestamp_ns"],sequence=value["sequence"],
                                  vx=vx,vy=vy,vyaw=yaw,stop=False,confidence=value["confidence"])
        self._previous=safe
        return {"intent":safe,"clamp_applied":bool(reasons),"reasons":reasons}
