import argparse
import json
import ssl
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from camera import Camera
from g29_control.config import load_config
from servo import Servo


HTML_PAGE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quest FPV</title>
  <style>
    body { margin: 0; background: #000; color: #fff; font-family: sans-serif; }
    #wrap { display: flex; flex-direction: column; height: 100vh; }
    #video { width: 100%; max-height: 62vh; object-fit: contain; background: #111; }
    #controls { flex: 1; padding: 8px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .panel { border: 1px solid #333; border-radius: 8px; padding: 8px; }
    .row { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
    button { font-size: 16px; padding: 10px 12px; border-radius: 8px; border: 1px solid #666; background: #222; color: #fff; }
    input[type=range] { width: 140px; }
    #status { font-size: 14px; color: #9f9; }
    #diag { font-size: 12px; color: #ddd; white-space: pre-wrap; }
  </style>
</head>
<body>
  <div id="wrap">
    <img id="video" src="/stream.mjpg" />
    <canvas id="xrCanvas" style="display:none;"></canvas>
    <div id="controls">
      <div class="panel">
        <div class="row"><strong>Manual Pan/Tilt</strong></div>
        <div class="row">
          <button onclick="delta(0, step)">Up</button>
          <button onclick="delta(-step, 0)">Left</button>
          <button onclick="home()">Home</button>
          <button onclick="delta(step, 0)">Right</button>
          <button onclick="delta(0, -step)">Down</button>
        </div>
        <div class="row">
          Step: <input id="stepRange" type="range" min="1" max="15" value="5" oninput="step=parseInt(this.value,10)">
          <span id="stepVal">5</span>
        </div>
      </div>
      <div class="panel">
        <div class="row"><strong>Head Tracking (Quest)</strong></div>
        <div class="row">
          <button id="gyroBtn" onclick="toggleGyro()">Enable Gyro Tracking</button>
          <button id="xrBtn" onclick="toggleXR()">Start XR Tracking</button>
          <button onclick="recenter()">Recenter</button>
        </div>
        <div class="row">
          Yaw sensitivity: <input id="yawRange" type="range" min="0.1" max="2.0" step="0.1" value="1.0">
          <span id="yawVal">1.0</span>
        </div>
        <div class="row">
          Pitch sensitivity: <input id="pitchRange" type="range" min="0.1" max="2.0" step="0.1" value="1.0">
          <span id="pitchVal">1.0</span>
        </div>
        <div id="status">Head tracking disabled</div>
        <div id="diag"></div>
      </div>
    </div>
  </div>
  <script>
    let step = 5;
    let gyroEnabled = false;
    let baseAlpha = null, baseBeta = null;
    let currentAlpha = null, currentBeta = null;
    let lastSendTs = 0;
    let orientationEventCount = 0;
    let headPacketsSent = 0;
    const minIntervalMs = 50; // 20Hz
    let xrSession = null;
    let xrRefSpace = null;
    let xrActive = false;
    let xrMode = '';
    let xrFrameCount = 0;
    let xrLastError = '';
    let baseYaw = null, basePitch = null;

    const stepRange = document.getElementById('stepRange');
    const stepVal = document.getElementById('stepVal');
    stepRange.addEventListener('input', () => { stepVal.textContent = stepRange.value; });

    const yawRange = document.getElementById('yawRange');
    const pitchRange = document.getElementById('pitchRange');
    const yawVal = document.getElementById('yawVal');
    const pitchVal = document.getElementById('pitchVal');
    yawRange.addEventListener('input', () => { yawVal.textContent = yawRange.value; });
    pitchRange.addEventListener('input', () => { pitchVal.textContent = pitchRange.value; });

    async function send(payload) {
      try {
        const resp = await fetch('/api/servo', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (payload.mode === 'head') {
          headPacketsSent += 1;
        }
        try {
          const data = await resp.json();
          window._lastServoState = data;
        } catch (_e) {}
      } catch (e) {}
    }

    function delta(dpan, dtilt) {
      send({mode: 'delta', dpan, dtilt});
    }

    function home() {
      send({mode: 'home'});
    }

    function recenter() {
      if (currentAlpha != null) baseAlpha = currentAlpha;
      if (currentBeta != null) baseBeta = currentBeta;
      baseYaw = null;
      basePitch = null;
      document.getElementById('status').textContent = 'Recentered';
    }

    function normalizeDeg(v) {
      while (v > 180) v -= 360;
      while (v < -180) v += 360;
      return v;
    }

    function onOrientation(ev) {
      orientationEventCount += 1;
      currentAlpha = ev.alpha; // yaw-like
      currentBeta = ev.beta;   // pitch-like
      if (!gyroEnabled || currentAlpha == null || currentBeta == null) return;

      if (baseAlpha == null || baseBeta == null) {
        baseAlpha = currentAlpha;
        baseBeta = currentBeta;
      }

      const now = Date.now();
      if (now - lastSendTs < minIntervalMs) return;
      lastSendTs = now;

      const dyaw = normalizeDeg(currentAlpha - baseAlpha);
      const dpitch = normalizeDeg(currentBeta - baseBeta);
      const yawSens = parseFloat(yawRange.value);
      const pitchSens = parseFloat(pitchRange.value);

      // Server clamps final angles; we only send offsets here.
      send({
        mode: 'head',
        yaw: dyaw * yawSens,
        pitch: dpitch * pitchSens
      });
      document.getElementById('status').textContent =
        `Head tracking enabled (alpha=${(currentAlpha ?? 0).toFixed(1)}, beta=${(currentBeta ?? 0).toFixed(1)})`;
    }

    function radToDeg(v) { return v * 180.0 / Math.PI; }
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function quaternionToYawPitch(qx, qy, qz, qw) {
      const siny_cosp = 2.0 * (qw * qz + qx * qy);
      const cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz);
      const yaw = Math.atan2(siny_cosp, cosy_cosp);

      const sinp = 2.0 * (qw * qy - qz * qx);
      const pitch = Math.asin(clamp(sinp, -1.0, 1.0));
      return { yawDeg: radToDeg(yaw), pitchDeg: radToDeg(pitch) };
    }

    function xrFrame(time, frame) {
      if (!xrSession || !xrRefSpace) return;
      xrFrameCount += 1;
      const pose = frame.getViewerPose(xrRefSpace);
      if (pose && pose.views && pose.views.length > 0) {
        const q = pose.views[0].transform.orientation;
        const yp = quaternionToYawPitch(q.x, q.y, q.z, q.w);
        if (baseYaw == null || basePitch == null) {
          baseYaw = yp.yawDeg;
          basePitch = yp.pitchDeg;
        }

        const now = Date.now();
        if (now - lastSendTs >= minIntervalMs) {
          lastSendTs = now;
          const dyaw = normalizeDeg(yp.yawDeg - baseYaw);
          const dpitch = normalizeDeg(yp.pitchDeg - basePitch);
          const yawSens = parseFloat(yawRange.value);
          const pitchSens = parseFloat(pitchRange.value);
          send({
            mode: 'head',
            yaw: dyaw * yawSens,
            pitch: dpitch * pitchSens
          });
          document.getElementById('status').textContent =
            `XR(${xrMode}) yaw=${yp.yawDeg.toFixed(1)}, pitch=${yp.pitchDeg.toFixed(1)}`;
        }
      }
      if (xrSession) xrSession.requestAnimationFrame(xrFrame);
    }

    async function startXR() {
      if (!navigator.xr) {
        document.getElementById('status').textContent = 'WebXR not available in this browser';
        return;
      }
      let mode = 'immersive-vr';
      let supported = await navigator.xr.isSessionSupported(mode);
      if (!supported) {
        mode = 'inline';
        supported = await navigator.xr.isSessionSupported(mode);
      }
      if (!supported) {
        document.getElementById('status').textContent = 'No supported WebXR mode';
        return;
      }

      xrSession = await navigator.xr.requestSession(mode);
      xrMode = mode;

      if (mode === 'immersive-vr') {
        const canvas = document.getElementById('xrCanvas');
        const gl = canvas.getContext('webgl', { xrCompatible: true, antialias: false });
        if (!gl) throw new Error('WebGL unavailable for immersive XR');
        await gl.makeXRCompatible();
        xrSession.updateRenderState({ baseLayer: new XRWebGLLayer(xrSession, gl) });
      }

      try {
        xrRefSpace = await xrSession.requestReferenceSpace('local');
      } catch (_e1) {
        try {
          xrRefSpace = await xrSession.requestReferenceSpace('local-floor');
        } catch (_e2) {
          xrRefSpace = await xrSession.requestReferenceSpace('viewer');
        }
      }

      xrActive = true;
      xrFrameCount = 0;
      xrLastError = '';
      document.getElementById('xrBtn').textContent = 'Stop XR Tracking';
      document.getElementById('status').textContent = `XR tracking started (${mode})`;
      baseYaw = null;
      basePitch = null;
      xrSession.addEventListener('end', () => {
        xrSession = null;
        xrRefSpace = null;
        xrActive = false;
        xrMode = '';
        document.getElementById('xrBtn').textContent = 'Start XR Tracking';
        document.getElementById('status').textContent = 'XR tracking stopped';
      });
      xrSession.requestAnimationFrame(xrFrame);
    }

    async function stopXR() {
      if (xrSession) {
        await xrSession.end();
      }
      xrActive = false;
      xrSession = null;
      xrRefSpace = null;
      document.getElementById('xrBtn').textContent = 'Start XR Tracking';
    }

    async function toggleXR() {
      try {
        if (!xrActive) await startXR();
        else await stopXR();
      } catch (e) {
        xrLastError = String(e);
        document.getElementById('status').textContent = `Could not start XR tracking: ${e}`;
      }
    }

    function updateDiag() {
      const secure = window.isSecureContext;
      const hasXR = !!navigator.xr;
      const gyroApi = typeof DeviceOrientationEvent !== 'undefined';
      const st = window._lastServoState || {};
      const txt =
`secureContext: ${secure}
navigator.xr: ${hasXR}
deviceOrientationApi: ${gyroApi}
xrActive: ${xrActive}
xrMode: ${xrMode || '-'}
xrFrames: ${xrFrameCount}
xrLastError: ${xrLastError || '-'}
gyroEvents: ${orientationEventCount}
headPacketsSent: ${headPacketsSent}
servoPanTilt: ${st.pan ?? '-'}, ${st.tilt ?? '-'}
servoOk: ${st.servo_ok ?? '-'}`;
      document.getElementById('diag').textContent = txt;
    }

    async function enableGyro() {
      if (typeof DeviceOrientationEvent !== 'undefined' &&
          typeof DeviceOrientationEvent.requestPermission === 'function') {
        const resp = await DeviceOrientationEvent.requestPermission();
        if (resp !== 'granted') throw new Error('Permission denied');
      }
      window.addEventListener('deviceorientation', onOrientation);
      gyroEnabled = true;
      orientationEventCount = 0;
      document.getElementById('gyroBtn').textContent = 'Disable Gyro Tracking';
      document.getElementById('status').textContent = 'Head tracking enabled';
      setTimeout(() => {
        if (gyroEnabled && orientationEventCount === 0) {
          document.getElementById('status').textContent =
            'No sensor data. In Quest browser, enable Motion Sensors permission for this site.';
        }
      }, 3000);
    }

    function disableGyro() {
      gyroEnabled = false;
      window.removeEventListener('deviceorientation', onOrientation);
      document.getElementById('gyroBtn').textContent = 'Enable Gyro Tracking';
      document.getElementById('status').textContent = 'Head tracking disabled';
    }

    async function toggleGyro() {
      try {
        if (!gyroEnabled) await enableGyro();
        else disableGyro();
      } catch (e) {
        document.getElementById('status').textContent = 'Could not enable sensors in browser';
      }
    }

    async function initPage() {
      try {
        const r = await fetch('/api/state');
        const s = await r.json();
        window._lastServoState = s;
        if (s.video_rotate_180) {
          document.getElementById('video').style.transform = 'rotate(180deg)';
        }
      } catch (_e) {}
      updateDiag();
      setInterval(updateDiag, 1000);
    }
    initPage();
  </script>
</body>
</html>
"""


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


class QuestFPVState:
    def __init__(self, config: dict):
        qcfg = config["quest_fpv"]
        self.min_angle = int(qcfg.get("min_angle", 0))
        self.max_angle = int(qcfg.get("max_angle", 180))
        self.home_pan = clamp(int(qcfg.get("home_pan", 90)), self.min_angle, self.max_angle)
        self.home_tilt = clamp(int(qcfg.get("home_tilt", 90)), self.min_angle, self.max_angle)
        self.yaw_to_deg = float(qcfg.get("yaw_to_deg", 0.5))
        self.pitch_to_deg = float(qcfg.get("pitch_to_deg", 0.5))
        self.invert_tilt = bool(qcfg.get("invert_tilt", False))
        self.video_rotate_180 = bool(qcfg.get("video_rotate_180", False))
        self.pan = self.home_pan
        self.tilt = self.home_tilt
        self._lock = threading.Lock()

        self.servo: Optional[Servo] = None
        self.servo_error: Optional[str] = None
        try:
            self.servo = Servo()
            pan_ch = str(qcfg.get("pan_channel", "0"))
            tilt_ch = str(qcfg.get("tilt_channel", "1"))
            self.pan_channel = pan_ch
            self.tilt_channel = tilt_ch
            self._apply_servo_locked()
        except Exception as exc:
            self.servo_error = str(exc)
            self.pan_channel = str(qcfg.get("pan_channel", "0"))
            self.tilt_channel = str(qcfg.get("tilt_channel", "1"))
            print(f"[quest_fpv] Servo unavailable: {exc}")

        cam_cfg = config["camera_stream"]
        width = int(cam_cfg.get("width", 1280))
        height = int(cam_cfg.get("height", 720))
        hflip = bool(cam_cfg.get("hflip", False))
        vflip = bool(cam_cfg.get("vflip", False))
        self.camera = Camera(stream_size=(width, height), hflip=hflip, vflip=vflip)
        self.camera.start_stream()

    def _apply_servo_locked(self) -> None:
        if self.servo is None:
            return
        self.servo.set_servo_pwm(self.pan_channel, self.pan)
        self.servo.set_servo_pwm(self.tilt_channel, self.tilt)

    def set_home(self) -> None:
        with self._lock:
            self.pan = self.home_pan
            self.tilt = self.home_tilt
            self._apply_servo_locked()

    def apply_delta(self, dpan: int, dtilt: int) -> None:
        with self._lock:
            if self.invert_tilt:
                dtilt = -int(dtilt)
            self.pan = clamp(self.pan + int(dpan), self.min_angle, self.max_angle)
            self.tilt = clamp(self.tilt + int(dtilt), self.min_angle, self.max_angle)
            self._apply_servo_locked()

    def apply_head(self, yaw: float, pitch: float) -> None:
        with self._lock:
            pan = self.home_pan + int(round(float(yaw) * self.yaw_to_deg))
            tilt_offset = int(round(float(pitch) * self.pitch_to_deg))
            if self.invert_tilt:
                tilt_offset = -tilt_offset
            tilt = self.home_tilt + tilt_offset
            self.pan = clamp(pan, self.min_angle, self.max_angle)
            self.tilt = clamp(tilt, self.min_angle, self.max_angle)
            self._apply_servo_locked()

    def apply_absolute(self, pan: int, tilt: int) -> None:
        with self._lock:
            self.pan = clamp(int(pan), self.min_angle, self.max_angle)
            self.tilt = clamp(int(tilt), self.min_angle, self.max_angle)
            self._apply_servo_locked()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "pan": self.pan,
                "tilt": self.tilt,
                "servo_ok": self.servo is not None,
                "servo_error": self.servo_error,
                "video_rotate_180": self.video_rotate_180,
            }

    def close(self) -> None:
        try:
            self.camera.stop_stream()
        except Exception:
            pass
        try:
            self.camera.close()
        except Exception:
            pass
        if self.servo is not None:
            try:
                self.servo.pwm_servo.close()
            except Exception:
                pass


class QuestHandler(BaseHTTPRequestHandler):
    state: QuestFPVState = None  # type: ignore[assignment]

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/state":
            self._send_json(self.state.snapshot())
            return
        if path == "/stream.mjpg":
            self.send_response(HTTPStatus.OK)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            try:
                while True:
                    frame = self.state.camera.get_frame()
                    if not frame:
                        continue
                    self.wfile.write(b"--FRAME\r\n")
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/servo":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            msg = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"ok": False, "error": "invalid_json"}, status=400)
            return

        mode = msg.get("mode", "")
        try:
            if mode == "home":
                self.state.set_home()
            elif mode == "delta":
                self.state.apply_delta(int(msg.get("dpan", 0)), int(msg.get("dtilt", 0)))
            elif mode == "head":
                self.state.apply_head(float(msg.get("yaw", 0.0)), float(msg.get("pitch", 0.0)))
            elif mode == "absolute":
                self.state.apply_absolute(int(msg.get("pan", 90)), int(msg.get("tilt", 90)))
            else:
                self._send_json({"ok": False, "error": "invalid_mode"}, status=400)
                return
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        self._send_json({"ok": True, **self.state.snapshot()})

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return


class RedirectHandler(BaseHTTPRequestHandler):
    https_port: int = 8443

    def _redirect(self) -> None:
        host = self.headers.get("Host", "")
        host_only = host.split(":", 1)[0] if host else "localhost"
        target = f"https://{host_only}:{self.https_port}{self.path}"
        self.send_response(HTTPStatus.MOVED_PERMANENTLY)
        self.send_header("Location", target)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._redirect()

    def do_POST(self) -> None:  # noqa: N802
        self._redirect()

    def do_HEAD(self) -> None:  # noqa: N802
        self._redirect()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Quest FPV web server (video + head/manual pan/tilt)")
    parser.add_argument("--config", default=str(ROOT / "g29_control" / "config.json"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    qcfg = cfg.get("quest_fpv", {})
    host = qcfg.get("host", "0.0.0.0")
    port = int(qcfg.get("port", 8080))
    https_enabled = bool(qcfg.get("https_enabled", False))
    https_port = int(qcfg.get("https_port", 8443))
    tls_cert = qcfg.get("tls_cert_path", "")
    tls_key = qcfg.get("tls_key_path", "")
    redirect_http = bool(qcfg.get("http_redirect_to_https", True))

    state = QuestFPVState(cfg)
    QuestHandler.state = state
    server = None
    redirect_server = None
    if https_enabled:
        cert_path = str((ROOT / tls_cert).resolve()) if tls_cert else ""
        key_path = str((ROOT / tls_key).resolve()) if tls_key else ""
        if not cert_path or not key_path or not Path(cert_path).exists() or not Path(key_path).exists():
            raise FileNotFoundError(
                "HTTPS enabled but certificate/key file not found. "
                "Set quest_fpv.tls_cert_path and quest_fpv.tls_key_path in config."
            )
        server = ThreadingHTTPServer((host, https_port), QuestHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        print(f"[quest_fpv] HTTPS server on https://{host}:{https_port}")
        if redirect_http:
            RedirectHandler.https_port = https_port
            redirect_server = ThreadingHTTPServer((host, port), RedirectHandler)
            threading.Thread(target=redirect_server.serve_forever, daemon=True).start()
            print(f"[quest_fpv] HTTP redirect on http://{host}:{port} -> HTTPS")
    else:
        server = ThreadingHTTPServer((host, port), QuestHandler)
        print(f"[quest_fpv] Open http://{host}:{port} from Quest browser")

    print("[quest_fpv] If host is 0.0.0.0, use Pi LAN IP in Quest URL")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping quest FPV server.")
    finally:
        if redirect_server is not None:
            redirect_server.shutdown()
            redirect_server.server_close()
        if server is not None:
            server.shutdown()
            server.server_close()
        state.close()


if __name__ == "__main__":
    main()
