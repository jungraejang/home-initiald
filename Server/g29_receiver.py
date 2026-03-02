import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from g29_control.config import load_config
from g29_control.protocol import ControlPacket, decode_packet
from motor import Ordinary_Car


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class BasicDriveMapper:
    def __init__(
        self,
        max_pwm: int,
        steer_gain: float,
        min_effective_pwm: int = 0,
        in_place_speed_threshold: float = 0.08,
        in_place_steer_threshold: float = 0.08,
        in_place_turn_pwm: int = 1200,
    ):
        self.max_pwm = int(max_pwm)
        self.steer_gain = float(steer_gain)
        self.min_effective_pwm = max(0, int(min_effective_pwm))
        self.in_place_speed_threshold = max(0.0, float(in_place_speed_threshold))
        self.in_place_steer_threshold = max(0.0, float(in_place_steer_threshold))
        self.in_place_turn_pwm = max(0, int(in_place_turn_pwm))

    def _apply_min_effective(self, pwm: int) -> int:
        if pwm == 0 or self.min_effective_pwm <= 0:
            return pwm
        if abs(pwm) < self.min_effective_pwm:
            return self.min_effective_pwm if pwm > 0 else -self.min_effective_pwm
        return pwm

    def compute_motor_duty(self, packet: ControlPacket) -> tuple[int, int, int, int]:
        speed = packet.throttle - packet.brake
        steer = packet.steer

        # Turn-in-place assist: if speed command is near zero but steering is commanded,
        # drive wheels in opposite directions so the car can rotate on the spot.
        if abs(speed) < self.in_place_speed_threshold and abs(steer) > self.in_place_steer_threshold:
            turn_pwm = int(round(abs(steer) * self.in_place_turn_pwm))
            turn_pwm = self._apply_min_effective(turn_pwm)
            if steer > 0:
                left_pwm, right_pwm = turn_pwm, -turn_pwm
            else:
                left_pwm, right_pwm = -turn_pwm, turn_pwm
            return left_pwm, left_pwm, right_pwm, right_pwm

        left = clamp(speed + self.steer_gain * steer, -1.0, 1.0)
        right = clamp(speed - self.steer_gain * steer, -1.0, 1.0)
        left_pwm = self._apply_min_effective(int(round(left * self.max_pwm)))
        right_pwm = self._apply_min_effective(int(round(right * self.max_pwm)))
        return left_pwm, left_pwm, right_pwm, right_pwm


def stop_car(car: Ordinary_Car) -> None:
    car.set_motor_model(0, 0, 0, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Raspberry Pi UDP receiver for G29 control")
    parser.add_argument("--config", default=str(ROOT / "g29_control" / "config.json"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    net = cfg["network"]
    mapping = cfg["mapping"]
    safety = cfg["safety"]
    log_cfg = cfg["logging"]

    listen_host = net["listen_host"]
    listen_port = int(net["listen_port"])
    timeout_s = max(0.05, float(safety["timeout_ms"]) / 1000.0)
    print_every_n = max(1, int(log_cfg["print_every_n"]))

    mapper = BasicDriveMapper(
        max_pwm=int(mapping["max_pwm"]),
        steer_gain=float(mapping["steer_gain"]),
        min_effective_pwm=int(mapping.get("min_effective_pwm", 0)),
        in_place_speed_threshold=float(mapping.get("in_place_speed_threshold", 0.08)),
        in_place_steer_threshold=float(mapping.get("in_place_steer_threshold", 0.08)),
        in_place_turn_pwm=int(mapping.get("in_place_turn_pwm", 1200)),
    )
    car = Ordinary_Car()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
    sock.bind((listen_host, listen_port))
    sock.setblocking(False)
    print(f"Listening on {listen_host}:{listen_port}, timeout={timeout_s:.3f}s")

    last_packet_time = 0.0
    last_seq = -1
    estop_latched = False
    stopped_by_timeout = False
    packet_count = 0

    try:
        while True:
            now = time.monotonic()
            # Heartbeat safety: stop if packets stop arriving.
            if last_packet_time > 0 and (now - last_packet_time) > timeout_s:
                if not stopped_by_timeout:
                    stop_car(car)
                    stopped_by_timeout = True
                    print("Failsafe stop: packet timeout")

            latest_packet = None
            malformed_count = 0

            # Drain UDP queue and keep the latest valid packet only.
            while True:
                try:
                    raw, source = sock.recvfrom(2048)
                except BlockingIOError:
                    break
                except OSError:
                    break

                try:
                    packet = decode_packet(raw)
                except Exception:
                    malformed_count += 1
                    continue

                if packet.seq <= last_seq:
                    continue
                latest_packet = packet

            if latest_packet is None:
                if malformed_count > 0:
                    stop_car(car)
                    print(f"Dropped {malformed_count} malformed packet(s)")
                time.sleep(0.001)
                continue

            stopped_by_timeout = False
            last_packet_time = time.monotonic()
            packet = latest_packet
            last_seq = packet.seq
            packet_count += 1

            if packet.estop:
                estop_latched = True
            if packet.reset_estop and packet.deadman:
                estop_latched = False

            if estop_latched or not packet.deadman:
                stop_car(car)
                if packet_count % print_every_n == 0:
                    print(
                        f"seq={packet.seq} deadman={int(packet.deadman)} "
                        f"estop_latched={int(estop_latched)} -> STOP"
                    )
                continue

            duty = mapper.compute_motor_duty(packet)
            car.set_motor_model(*duty)

            if packet_count % print_every_n == 0:
                print(
                    f"seq={packet.seq} steer={packet.steer:+.2f} throttle={packet.throttle:.2f} "
                    f"brake={packet.brake:.2f} duty={duty}"
                )
    except KeyboardInterrupt:
        print("\nStopping G29 receiver.")
    finally:
        stop_car(car)
        car.close()
        sock.close()


if __name__ == "__main__":
    main()
