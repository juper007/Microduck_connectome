"""Phase-5 freshness, health, and decoder-liveness watchdog."""

from collections.abc import Mapping
import json
from pathlib import Path
from types import MappingProxyType
import weakref

from .control_contracts import (
    ControlContractError,
    make_behavior_intent,
    validate_behavior_intent,
    validate_neural_readout,
)


class WatchdogError(ValueError):
    """Trusted watchdog configuration/tick metadata is invalid."""


class WatchdogOutput(Mapping):
    """Immutable output minted only by ``ControllerWatchdog.tick``."""

    __slots__ = ("__values", "__weakref__")
    _fields = ("intent", "watchdog_state", "stale_reason", "decoder_alive")

    def __new__(cls, *args, **kwargs):
        raise TypeError("WatchdogOutput can only be created by ControllerWatchdog.tick")

    def __setattr__(self, name, value):
        raise AttributeError("WatchdogOutput is immutable")

    def __getitem__(self, key):
        return self.__values[key]

    def __iter__(self):
        return iter(self._fields)

    def __len__(self):
        return len(self._fields)


def load_watchdog_config(path):
    try:
        value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as error:
        raise WatchdogError("cannot load watchdog config") from error
    fields={"schema_version","neural_readout_ttl_ms","behavior_intent_ttl_ms","source","scope"}
    if not isinstance(value,Mapping) or set(value)!=fields:
        raise WatchdogError("watchdog config fields mismatch")
    if value["schema_version"]!="watchdog-v1" or value["source"]!="male-cns-controller":
        raise WatchdogError("watchdog schema/source mismatch")
    if type(value["neural_readout_ttl_ms"]) is not int or value["neural_readout_ttl_ms"]!=100:
        raise WatchdogError("neural_readout_ttl_ms must remain 100")
    if type(value["behavior_intent_ttl_ms"]) is not int or value["behavior_intent_ttl_ms"]!=100:
        raise WatchdogError("behavior_intent_ttl_ms must remain 100")
    return value


class ControllerWatchdog:
    """Republish only fresh healthy behavior; otherwise emit a current stop intent."""

    def __init__(self,config):
        config=load_watchdog_config(config) if isinstance(config,(str,Path)) else config
        if not isinstance(config,Mapping):
            raise WatchdogError("config must be a validated mapping or path")
        if config.get("neural_readout_ttl_ms")!=100 or config.get("behavior_intent_ttl_ms")!=100:
            raise WatchdogError("watchdog TTLs must remain 100 ms")
        self.neural_ttl_ns=100_000_000
        self.behavior_ttl_ns=100_000_000
        self.reset()

    def reset(self):
        self._neural=None
        self._behavior=None
        self._neural_fault=None
        self._behavior_fault=None
        self._decoder_alive=True
        self._last_neural_meta=None
        self._last_behavior_meta=None
        self._last_output_timestamp=None
        self._last_output_sequence=None

    @staticmethod
    def _newer(sample,previous_meta):
        return previous_meta is None or (
            sample["timestamp_ns"]>previous_meta[0]
            and sample["sequence"]>previous_meta[1]
        )

    def observe_neural(self,readout):
        try:
            value=validate_neural_readout(readout)
        except ControlContractError:
            self._neural=None
            self._neural_fault="invalid_neural"
            return False
        if not self._newer(value,self._last_neural_meta):
            self._neural=None
            self._neural_fault="nonmonotonic_neural"
            return False
        self._neural=value
        self._last_neural_meta=(value["timestamp_ns"],value["sequence"])
        self._neural_fault=None
        return True

    def observe_behavior(self,intent):
        try:
            value=validate_behavior_intent(intent)
        except ControlContractError:
            self._behavior=None
            self._behavior_fault="invalid_behavior"
            return False
        if not self._newer(value,self._last_behavior_meta):
            self._behavior=None
            self._behavior_fault="nonmonotonic_behavior"
            return False
        self._behavior=value
        self._last_behavior_meta=(value["timestamp_ns"],value["sequence"])
        self._behavior_fault=None
        return True

    def mark_decoder_crashed(self,returncode):
        if type(returncode) is not int or returncode==0:
            raise WatchdogError("crash returncode must be a nonzero integer")
        self._decoder_alive=False
        self._neural=None
        self._behavior=None

    def recover_decoder(self):
        self._decoder_alive=True
        self._neural=None
        self._behavior=None
        self._neural_fault=None
        self._behavior_fault=None
        self._last_neural_meta=None
        self._last_behavior_meta=None

    def _tick_metadata(self,now_ns,output_sequence):
        if type(now_ns) is not int or now_ns<0:
            raise WatchdogError("now_ns must be a non-negative integer")
        if type(output_sequence) is not int or output_sequence<0:
            raise WatchdogError("output_sequence must be a non-negative integer")
        if self._last_output_timestamp is not None:
            if now_ns<=self._last_output_timestamp:
                raise WatchdogError("watchdog tick timestamp must increase strictly")
            if output_sequence<=self._last_output_sequence:
                raise WatchdogError("watchdog output sequence must increase strictly")



def _install_tick_boundary():
    """Keep the mint registry inside ``tick``'s closure, not in module state."""
    minted = {}

    def forget(output_id):
        minted.pop(output_id, None)

    def tick(self, *, now_ns, output_sequence):
        self._tick_metadata(now_ns, output_sequence)
        reason = None
        if not self._decoder_alive:
            reason = "decoder_crash"
        elif self._neural_fault is not None:
            reason = self._neural_fault
        elif self._behavior_fault is not None:
            reason = self._behavior_fault
        elif self._neural is None:
            reason = "missing_neural"
        elif self._behavior is None:
            reason = "missing_behavior"
        elif not self._neural["runtime_healthy"]:
            reason = "runtime_unhealthy"
        elif self._neural["timestamp_ns"] > now_ns:
            reason = "future_neural"
        elif self._behavior["timestamp_ns"] > now_ns:
            reason = "future_behavior"
        elif now_ns - self._neural["timestamp_ns"] > self.neural_ttl_ns:
            reason = "stale_neural"
        elif now_ns - self._behavior["timestamp_ns"] > self.behavior_ttl_ns:
            reason = "stale_behavior"

        if reason is None:
            source = self._behavior
            intent = make_behavior_intent(
                timestamp_ns=now_ns, sequence=output_sequence,
                vx=source["vx"], vy=source["vy"], vyaw=source["vyaw"],
                stop=source["stop"], confidence=source["confidence"],
            )
            state = "healthy"
        else:
            intent = make_behavior_intent(
                timestamp_ns=now_ns, sequence=output_sequence,
                vx=0.0, vy=0.0, vyaw=0.0, stop=True, confidence=0.0,
            )
            state = "safe_stop"
        self._last_output_timestamp = now_ns
        self._last_output_sequence = output_sequence
        result = object.__new__(WatchdogOutput)
        values = MappingProxyType({
            "intent": MappingProxyType(dict(intent)),
            "watchdog_state": state,
            "stale_reason": reason,
            "decoder_alive": self._decoder_alive,
        })
        object.__setattr__(result, "_WatchdogOutput__values", values)
        output_id = id(result)
        minted[output_id] = (
            weakref.ref(
                result, lambda _reference, output_id=output_id: forget(output_id)
            ),
            values,
        )
        return result

    def is_authentic(output):
        registration = minted.get(id(output))
        if type(output) is not WatchdogOutput or registration is None:
            return False
        reference, values = registration
        return (
            reference() is output
            and getattr(output, "_WatchdogOutput__values", None) is values
        )

    ControllerWatchdog.tick = tick
    return is_authentic


_is_authentic_watchdog_output = _install_tick_boundary()
del _install_tick_boundary
