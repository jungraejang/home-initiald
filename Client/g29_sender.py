import argparse
import socket
import sys
import time
from pathlib import Path
from typing import Tuple

import pygame

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from g29_control.config import load_config
from g29_control.protocol import ControlPacket


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def map_axis_signed(raw: float, axis_min: float, axis_max: float, invert: bool, deadzone: float) -> float:
    if axis_max == axis_min:
        return 0.0
    scaled = ((raw - axis_min) / (axis_max - axis_min)) * 2.0 - 1.0
    scaled = clamp(scaled, -1.0, 1.0)
    if invert:
        scaled = -scaled
    if abs(scaled) < deadzone:
        return 0.0
    return scaled


def map_axis_01(raw: float, axis_min: float, axis_max: float, invert: bool) -> float:
    if axis_max == axis_min:
        return 0.0
    scaled = (raw - axis_min) / (axis_max - axis_min)
    scaled = clamp(scaled, 0.0, 1.0)
    if invert:
        scaled = 1.0 - scaled
    return scaled


def find_g29_joystick() -> pygame.joystick.Joystick:
    pygame.joystick.init()
    joystick_count = pygame.joystick.get_count()
    if joystick_count == 0:
        raise RuntimeError("No joystick/game controller detected.")
    preferred = None
    for idx in range(joystick_count):
        js = pygame.joystick.Joystick(idx)
        js.init()
        name = js.get_name().lower()
        if "g29" in name or ("logitech" in name and "wheel" in name):
            preferred = js
            break
    if preferred is None:
        preferred = pygame.joystick.Joystick(0)
        preferred.init()
    return preferred


def calibrate(joystick: pygame.joystick.Joystick, seconds: float) -> Tuple[dict, dict]:
    print(f"Calibrating for {seconds:.1f}s. Move wheel full left/right and press/release pedals.")
    axis_min = {}
    axis_max = {}
    axis_count = joystick.get_numaxes()
    for i in range(axis_count):
        raw = joystick.get_axis(i)
        axis_min[i] = raw
        axis_max[i] = raw

    start = time.monotonic()
    while time.monotonic() - start < seconds:
        pygame.event.pump()
        for i in range(axis_count):
            raw = joystick.get_axis(i)
            axis_min[i] = min(axis_min[i], raw)
            axis_max[i] = max(axis_max[i], raw)
        time.sleep(0.01)
    return axis_min, axis_max


def main() -> None:
    parser = argparse.ArgumentParser(description="G29 UDP sender for Raspberry Pi RC car")
    parser.add_argument("--config", default=str(ROOT / "g29_control" / "config.json"))
    parser.add_argument("--calibrate-seconds", type=float, default=0.0)
    args = parser.parse_args()

    cfg = load_config(args.config)
    net = cfg["network"]
    inp = cfg["input"]
    log_cfg = cfg["logging"]

    pygame.init()
    joystick = find_g29_joystick()
    print(f"Using controller: {joystick.get_name()}")
    print(f"Axes={joystick.get_numaxes()} Buttons={joystick.get_numbuttons()}")

    if args.calibrate_seconds > 0:
        mins, maxs = calibrate(joystick, args.calibrate_seconds)
        print("Calibration results:")
        for k in sorted(mins.keys()):
            print(f"  axis {k}: min={mins[k]:.4f} max={maxs[k]:.4f}")

    target = (net["pi_host"], int(net["pi_port"]))
    hz = max(1, int(net["hz"]))
    period = 1.0 / hz
    print_every_n = max(1, int(log_cfg["print_every_n"]))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Sending to {target[0]}:{target[1]} at {hz} Hz")

    seq = 0
    send_count = 0
    log_window_start = time.monotonic()
    try:
        while True:
            loop_start = time.monotonic()
            pygame.event.pump()
            steer_raw = joystick.get_axis(int(inp["steer_axis"]))
            throttle_raw = joystick.get_axis(int(inp["throttle_axis"]))
            brake_raw = joystick.get_axis(int(inp["brake_axis"]))

            steer = map_axis_signed(
                steer_raw,
                float(inp["axis_min"]["steer"]),
                float(inp["axis_max"]["steer"]),
                bool(inp["invert_steer"]),
                float(inp["deadzone"]),
            )
            throttle = map_axis_01(
                throttle_raw,
                float(inp["axis_min"]["throttle"]),
                float(inp["axis_max"]["throttle"]),
                bool(inp["invert_throttle"]),
            )
            brake = map_axis_01(
                brake_raw,
                float(inp["axis_min"]["brake"]),
                float(inp["axis_max"]["brake"]),
                bool(inp["invert_brake"]),
            )

            deadman = bool(joystick.get_button(int(inp["deadman_button"])))
            estop = bool(joystick.get_button(int(inp["estop_button"])))
            reset_estop = bool(joystick.get_button(int(inp["reset_estop_button"])))

            packet = ControlPacket.create(
                seq=seq,
                steer=steer,
                throttle=throttle,
                brake=brake,
                deadman=deadman,
                estop=estop,
                reset_estop=reset_estop,
            )
            sock.sendto(packet.to_bytes(), target)
            seq += 1
            send_count += 1

            if send_count % print_every_n == 0:
                elapsed = max(1e-6, time.monotonic() - log_window_start)
                rate = print_every_n / elapsed
                log_window_start = time.monotonic()
                print(
                    f"seq={packet.seq} steer={packet.steer:+.2f} "
                    f"throttle={packet.throttle:.2f} brake={packet.brake:.2f} "
                    f"deadman={int(packet.deadman)} estop={int(packet.estop)} tx={rate:.1f}Hz"
                )

            loop_elapsed = time.monotonic() - loop_start
            sleep_time = period - loop_elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        print("\nStopping G29 sender.")
    finally:
        sock.close()
        pygame.quit()


if __name__ == "__main__":
    main()
