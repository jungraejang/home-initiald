import argparse
import socket
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from g29_control.config import load_config


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("Socket closed by server")
        data += chunk
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="PC viewer for Pi camera stream")
    parser.add_argument("--config", default="g29_control/config.json")
    parser.add_argument("--host", default=None, help="Override Pi host/IP")
    parser.add_argument("--port", type=int, default=None, help="Override camera stream port")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cam_cfg = cfg.get("camera_stream", {})
    net_cfg = cfg.get("network", {})

    host = args.host or cam_cfg.get("host_client", net_cfg.get("pi_host", "127.0.0.1"))
    port = int(args.port or cam_cfg.get("port", 8001))
    client_hflip = bool(cam_cfg.get("client_hflip", False))
    client_vflip = bool(cam_cfg.get("client_vflip", False))
    display_width = int(cam_cfg.get("client_display_width", 0))
    display_height = int(cam_cfg.get("client_display_height", 0))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.connect((host, port))
    print(f"Connected to camera stream {host}:{port}")
    print(f"Viewer flip settings: hflip={int(client_hflip)} vflip={int(client_vflip)}")
    if display_width > 0 and display_height > 0:
        print(f"Viewer display size: {display_width}x{display_height}")

    cv2.namedWindow("Pi Camera Stream", cv2.WINDOW_NORMAL)

    frame_count = 0
    t0 = time.monotonic()

    try:
        while True:
            header = recv_exact(sock, 4)
            (length,) = struct.unpack("<I", header)
            jpg = recv_exact(sock, length)
            image = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                continue

            if client_hflip and client_vflip:
                image = cv2.flip(image, -1)
            elif client_hflip:
                image = cv2.flip(image, 1)
            elif client_vflip:
                image = cv2.flip(image, 0)

            if display_width > 0 and display_height > 0:
                image = cv2.resize(image, (display_width, display_height), interpolation=cv2.INTER_LINEAR)

            frame_count += 1
            if frame_count % 30 == 0:
                elapsed = max(1e-6, time.monotonic() - t0)
                fps = frame_count / elapsed
                cv2.setWindowTitle("Pi Camera Stream", f"Pi Camera Stream - {fps:.1f} FPS")

            cv2.imshow("Pi Camera Stream", image)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
