import json
import time
from dataclasses import dataclass
from typing import Any, Dict


PROTOCOL_VERSION = 1


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class ControlPacket:
    seq: int
    timestamp_ms: int
    steer: float
    throttle: float
    brake: float
    deadman: bool
    estop: bool
    reset_estop: bool = False
    version: int = PROTOCOL_VERSION

    @classmethod
    def create(
        cls,
        seq: int,
        steer: float,
        throttle: float,
        brake: float,
        deadman: bool,
        estop: bool,
        reset_estop: bool = False,
    ) -> "ControlPacket":
        return cls(
            seq=int(seq),
            timestamp_ms=int(time.time() * 1000),
            steer=_clamp(float(steer), -1.0, 1.0),
            throttle=_clamp(float(throttle), 0.0, 1.0),
            brake=_clamp(float(brake), 0.0, 1.0),
            deadman=bool(deadman),
            estop=bool(estop),
            reset_estop=bool(reset_estop),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "seq": self.seq,
            "timestamp_ms": self.timestamp_ms,
            "steer": self.steer,
            "throttle": self.throttle,
            "brake": self.brake,
            "deadman": self.deadman,
            "estop": self.estop,
            "reset_estop": self.reset_estop,
        }

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8")


def decode_packet(raw: bytes) -> ControlPacket:
    payload = json.loads(raw.decode("utf-8"))
    required = {
        "version",
        "seq",
        "timestamp_ms",
        "steer",
        "throttle",
        "brake",
        "deadman",
        "estop",
    }
    missing = required.difference(payload.keys())
    if missing:
        raise ValueError(f"Missing packet fields: {sorted(missing)}")
    if int(payload["version"]) != PROTOCOL_VERSION:
        raise ValueError(f"Unsupported protocol version: {payload['version']}")

    packet = ControlPacket(
        version=int(payload["version"]),
        seq=int(payload["seq"]),
        timestamp_ms=int(payload["timestamp_ms"]),
        steer=float(payload["steer"]),
        throttle=float(payload["throttle"]),
        brake=float(payload["brake"]),
        deadman=bool(payload["deadman"]),
        estop=bool(payload["estop"]),
        reset_estop=bool(payload.get("reset_estop", False)),
    )
    packet.steer = _clamp(packet.steer, -1.0, 1.0)
    packet.throttle = _clamp(packet.throttle, 0.0, 1.0)
    packet.brake = _clamp(packet.brake, 0.0, 1.0)
    return packet
