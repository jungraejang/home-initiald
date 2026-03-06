import argparse
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from camera import Camera
from g29_control.config import load_config


def run_server(config_path: str) -> None:
    cfg = load_config(config_path)
    cam_cfg = cfg.get("camera_stream", {})
    host = cam_cfg.get("host", "0.0.0.0")
    port = int(cam_cfg.get("port", 8001))
    width = int(cam_cfg.get("width", 640))
    height = int(cam_cfg.get("height", 360))
    hflip = bool(cam_cfg.get("hflip", False))
    vflip = bool(cam_cfg.get("vflip", False))

    try:
        camera = Camera(stream_size=(width, height), hflip=hflip, vflip=vflip)
    except Exception as exc:
        print("Failed to initialize Pi camera stream.")
        print(f"Reason: {exc}")
        print("Checks:")
        print("1) Verify camera is connected to CSI port and ribbon orientation is correct.")
        print("2) Run: libcamera-hello --list-cameras")
        print("3) Make sure camera interface is enabled and reboot Pi if you changed settings.")
        print("4) Stop other processes using camera (only one owner at a time).")
        raise
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(1)
    print(f"Camera stream listening on {host}:{port} at {width}x{height}")

    try:
        while True:
            client_socket, client_addr = server_socket.accept()
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"Viewer connected: {client_addr}")
            camera.start_stream()
            try:
                while True:
                    frame = camera.get_frame()
                    if not frame:
                        continue
                    header = struct.pack("<I", len(frame))
                    client_socket.sendall(header)
                    client_socket.sendall(frame)
            except (BrokenPipeError, ConnectionResetError, OSError):
                print(f"Viewer disconnected: {client_addr}")
            finally:
                try:
                    client_socket.close()
                except OSError:
                    pass
                camera.stop_stream()
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopping camera stream server.")
    finally:
        try:
            camera.close()
        finally:
            server_socket.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Pi camera TCP stream server")
    parser.add_argument("--config", default=str(ROOT / "g29_control" / "config.json"))
    args = parser.parse_args()
    run_server(args.config)


if __name__ == "__main__":
    main()
