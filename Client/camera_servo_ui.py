import argparse
import json
import socket
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from g29_control.config import load_config


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


class ServoControlUI:
    def __init__(
        self,
        host: str,
        port: int,
        step: int,
        min_angle: int,
        max_angle: int,
        home_pan: int,
        home_tilt: int,
        invert_tilt: bool,
    ):
        self.target = (host, port)
        self.step = step
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.invert_tilt = invert_tilt
        self.home_pan = clamp(home_pan, min_angle, max_angle)
        self.home_tilt = clamp(home_tilt, min_angle, max_angle)
        self.pan = clamp(home_pan, min_angle, max_angle)
        self.tilt = clamp(home_tilt, min_angle, max_angle)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.root = tk.Tk()
        self.root.title("Camera Pan/Tilt")
        self.root.geometry("260x180")
        self.root.resizable(False, False)

        self.status = tk.StringVar()
        self._update_status()

        btn_up = tk.Button(self.root, text="Up", width=10, command=lambda: self.move(0, +self.step))
        btn_left = tk.Button(self.root, text="Left", width=10, command=lambda: self.move(-self.step, 0))
        btn_home = tk.Button(self.root, text="Home", width=10, command=self.home)
        btn_right = tk.Button(self.root, text="Right", width=10, command=lambda: self.move(+self.step, 0))
        btn_down = tk.Button(self.root, text="Down", width=10, command=lambda: self.move(0, -self.step))

        btn_up.grid(row=0, column=1, padx=8, pady=8)
        btn_left.grid(row=1, column=0, padx=8, pady=8)
        btn_home.grid(row=1, column=1, padx=8, pady=8)
        btn_right.grid(row=1, column=2, padx=8, pady=8)
        btn_down.grid(row=2, column=1, padx=8, pady=8)

        tk.Label(self.root, textvariable=self.status).grid(row=3, column=0, columnspan=3, pady=8)
        tk.Label(self.root, text="Hotkeys: Arrow keys + H (home)").grid(row=4, column=0, columnspan=3)

        self.root.bind("<Left>", lambda _e: self.move(-self.step, 0))
        self.root.bind("<Right>", lambda _e: self.move(+self.step, 0))
        self.root.bind("<Up>", lambda _e: self.move(0, +self.step))
        self.root.bind("<Down>", lambda _e: self.move(0, -self.step))
        self.root.bind("<h>", lambda _e: self.home())
        self.root.bind("<H>", lambda _e: self.home())

        self.send()

    def _update_status(self) -> None:
        self.status.set(f"Pan: {self.pan}   Tilt: {self.tilt}")

    def send(self) -> None:
        payload = {"type": "servo_cmd", "pan": self.pan, "tilt": self.tilt}
        self.sock.sendto(json.dumps(payload).encode("utf-8"), self.target)
        self._update_status()

    def move(self, pan_delta: int, tilt_delta: int) -> None:
        if self.invert_tilt:
            tilt_delta = -tilt_delta
        self.pan = clamp(self.pan + pan_delta, self.min_angle, self.max_angle)
        self.tilt = clamp(self.tilt + tilt_delta, self.min_angle, self.max_angle)
        self.send()

    def home(self) -> None:
        self.pan = self.home_pan
        self.tilt = self.home_tilt
        self.send()

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="PC arrow-button UI for camera pan/tilt")
    parser.add_argument("--config", default=str(ROOT / "g29_control" / "config.json"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    scfg = cfg.get("servo_control", {})
    net_cfg = cfg.get("network", {})
    host = scfg.get("pi_host", net_cfg.get("pi_host", "127.0.0.1"))
    port = int(scfg.get("pi_port", 5006))
    step = int(scfg.get("step", 5))
    min_angle = int(scfg.get("min_angle", 0))
    max_angle = int(scfg.get("max_angle", 180))
    home_pan = int(scfg.get("home_pan", 90))
    home_tilt = int(scfg.get("home_tilt", 90))
    invert_tilt = bool(scfg.get("invert_tilt", False))

    ui = ServoControlUI(
        host=host,
        port=port,
        step=step,
        min_angle=min_angle,
        max_angle=max_angle,
        home_pan=home_pan,
        home_tilt=home_tilt,
        invert_tilt=invert_tilt,
    )
    print(f"Servo UI sending to {host}:{port} (invert_tilt={int(invert_tilt)})")
    ui.run()


if __name__ == "__main__":
    main()
