"""Deterministic structured Phase-5 command trace logging."""

from collections.abc import Mapping, Sequence
import json

from .control_contracts import (
    ControlContractError,
    validate_behavior_intent,
    validate_neural_readout,
)


class CommandLoggerError(ValueError):
    """A command-trace record violates the P5-06 evidence contract."""


def _identity(value):
    if not isinstance(value, Mapping) or not value:
        raise CommandLoggerError("config_identity must be a non-empty mapping")
    result={}
    sensitive=("secret","token","password","credential","api_key")
    for key,item in value.items():
        if not isinstance(key,str) or not key.strip():
            raise CommandLoggerError("config identity keys must be nonblank strings")
        if any(word in key.lower() for word in sensitive):
            raise CommandLoggerError("config identity must not contain credential fields")
        if not isinstance(item,str) or not item.strip():
            raise CommandLoggerError("config identity values must be nonblank strings")
        if item.startswith(("/", "~/")) or (len(item)>2 and item[1]==":" and item[2] in ("\\","/")):
            raise CommandLoggerError("config identity must not contain local filesystem paths")
        result[key]=item
    return dict(sorted(result.items()))


def _intent(value,label):
    if value is None:
        return None
    try:
        return validate_behavior_intent(value)
    except ControlContractError as error:
        raise CommandLoggerError(f"{label} is invalid") from error


def _neural(value):
    if value is None:
        return None
    try:
        return validate_neural_readout(value)
    except ControlContractError as error:
        raise CommandLoggerError("neural_readout is invalid") from error


def _reasons(value):
    if not isinstance(value, Sequence) or isinstance(value,(str,bytes)):
        raise CommandLoggerError("clamp reasons must be a sequence")
    result=[]
    for item in value:
        if not isinstance(item,str) or not item.strip():
            raise CommandLoggerError("clamp reasons must be nonblank strings")
        result.append(item)
    if len(set(result))!=len(result):
        raise CommandLoggerError("clamp reasons must not contain duplicates")
    return result


class CommandTrace:
    """Retain detached reconstructible records and emit canonical JSONL."""

    def __init__(self,config_identity):
        self._config_identity=_identity(config_identity)
        self._records=[]

    def append(self,*,neural_readout,pre_safety_intent,safety_result,watchdog_result):
        neural=_neural(neural_readout)
        pre=_intent(pre_safety_intent,"pre_safety_intent")

        post=None
        clamp_applied=False
        clamp_reasons=[]
        if safety_result is not None:
            if not isinstance(safety_result,Mapping) or set(safety_result)!={"intent","clamp_applied","reasons"}:
                raise CommandLoggerError("safety_result fields mismatch")
            if type(safety_result["clamp_applied"]) is not bool:
                raise CommandLoggerError("clamp_applied must be bool")
            post=_intent(safety_result["intent"],"post_safety_intent")
            clamp_reasons=_reasons(safety_result["reasons"])
            clamp_applied=safety_result["clamp_applied"]
            if clamp_applied!=bool(clamp_reasons):
                raise CommandLoggerError("clamp_applied must match presence of clamp reasons")

        if not isinstance(watchdog_result,Mapping) or set(watchdog_result)!={"intent","watchdog_state","stale_reason","decoder_alive"}:
            raise CommandLoggerError("watchdog_result fields mismatch")
        final=_intent(watchdog_result["intent"],"watchdog_intent")
        state=watchdog_result["watchdog_state"]
        reason=watchdog_result["stale_reason"]
        alive=watchdog_result["decoder_alive"]
        if state not in ("healthy","safe_stop") or type(alive) is not bool:
            raise CommandLoggerError("invalid watchdog state/liveness")
        if reason is not None and (not isinstance(reason,str) or not reason.strip()):
            raise CommandLoggerError("stale_reason must be null or nonblank string")
        if state=="healthy":
            if reason is not None or not alive:
                raise CommandLoggerError("healthy watchdog result is inconsistent")
        else:
            if reason is None or not final["stop"] or any(final[name]!=0.0 for name in ("vx","vy","vyaw")):
                raise CommandLoggerError("safe_stop watchdog result must be reasoned zero-motion stop")

        timestamp=final["timestamp_ns"]
        sequence=final["sequence"]
        if self._records:
            previous=self._records[-1]
            if timestamp<=previous["timestamp_ns"] or sequence<=previous["sequence"]:
                raise CommandLoggerError("trace timestamp/sequence must increase strictly")

        record={
            "timestamp_ns":timestamp,
            "sequence":sequence,
            "neural_readout":neural,
            "pre_safety_intent":pre,
            "post_safety_intent":post,
            "watchdog_intent":final,
            "stop_state":final["stop"],
            "runtime_healthy":neural["runtime_healthy"] if neural is not None else False,
            "watchdog_state":state,
            "decoder_alive":alive,
            "clamp_applied":clamp_applied,
            "clamp_reasons":clamp_reasons,
            "stale_reason":reason,
            "source":final["source"],
            "config_identity":dict(self._config_identity),
        }
        # JSON round-trip creates a detached tree and proves JSON-safety.
        detached=json.loads(json.dumps(record,sort_keys=True,separators=(",",":"),allow_nan=False))
        self._records.append(detached)

    def records(self):
        return json.loads(json.dumps(self._records,sort_keys=True,separators=(",",":"),allow_nan=False))

    def to_jsonl(self):
        return "".join(
            json.dumps(record,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)+"\n"
            for record in self._records
        )
