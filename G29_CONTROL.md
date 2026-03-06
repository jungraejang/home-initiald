# G29 Steering Wheel Control (PC -> Raspberry Pi)

This adds a new low-latency UDP control path for driving your car with a Logitech G29 wheel and pedals.

## Files

- PC sender: `Client/g29_sender.py`
- Pi receiver: `Server/g29_receiver.py`
- Shared protocol/config: `g29_control/protocol.py`, `g29_control/config.py`
- Config template: `g29_control/config.example.json`

## 1) Install dependencies

### Windows PC

```bash
python -m pip install pygame
```

### Raspberry Pi

No extra package is required for the receiver script itself.

## 2) Create config

Copy `g29_control/config.example.json` to `g29_control/config.json`, then edit:

- `network.pi_host`: your Pi IP address
- `network.pi_port` and `network.listen_port`: keep same value on both sides
- `input.*`: axis/button mapping for your G29
- `input.require_deadman`: set `true` for hold-to-drive safety, `false` for quick bench testing

## 3) Start receiver on Raspberry Pi

```bash
python3 Server/g29_receiver.py --config g29_control/config.json
```

## 4) Start sender on Windows PC

```bash
python Client/g29_sender.py --config g29_control/config.json
```

## 5) Real-time camera feed

### Start camera stream on Raspberry Pi

```bash
python3 Server/camera_stream_server.py --config g29_control/config.json
```

### View camera feed on PC

```bash
python Client/camera_stream_client.py --config g29_control/config.json
```

Press `q` in the viewer window to close.

## 6) One-command master launcher

Instead of running separate scripts manually, use:

```bash
python master_control.py --role pi --config g29_control/config.json
```

on Raspberry Pi, and:

```bash
python master_control.py --role pc --config g29_control/config.json
```

on Windows PC.

Modes:
- `--role pi`: starts `Server/g29_receiver.py` + `Server/camera_stream_server.py` + `Server/servo_control_server.py`
- `--role pc`: starts `Client/g29_sender.py` + `Client/camera_stream_client.py` + `Client/camera_servo_ui.py`
- `--role all`: starts everything on one machine (debug/testing only)
- `--no-camera`: run control only (skip camera processes)
- `--quest-fpv`: run Quest web FPV server on Pi instead of legacy PC camera/servo UI stack

Press `Ctrl+C` in the master terminal to stop all child processes together.

If camera viewer fails with `No module named 'cv2'`, install on PC:

```bash
python -m pip install opencv-python
```

Optional calibration readout:

```bash
python Client/g29_sender.py --config g29_control/config.json --calibrate-seconds 8
```

Use calibration output to update `input.axis_min` / `input.axis_max`.

## Safety behavior

- If no valid packet arrives for `timeout_ms`, the Pi stops the motors.
- If `input.require_deadman=true` and deadman button is not pressed, the Pi stops the motors.
- If e-stop button is pressed once, receiver latches stop mode.
- To clear latched e-stop, press reset-e-stop button while holding deadman.

## Drive mapping

- `speed = throttle - brake`
- `left = speed + steer_gain * steer`
- `right = speed - steer_gain * steer`
- Applied as `set_motor_model(left, left, right, right)` with PWM clamping
- When `|speed|` is very small but steering is commanded, receiver applies in-place turn assist.

### Latency and steering tuning

- Increase `network.hz` (for example `80`) to reduce command interval.
- `mapping.min_effective_pwm`: minimum non-zero PWM to overcome motor deadband.
- `mapping.in_place_speed_threshold`: below this speed, allow turn-in-place mode.
- `mapping.in_place_steer_threshold`: ignore tiny steering noise near center.
- `mapping.in_place_turn_pwm`: turn-in-place strength.
- `mapping.forward_steer_boost`: adds steering authority as forward speed increases.
- `mapping.max_steer_gain`: caps boosted steering gain to keep control stable.
- `camera_stream.width/height`: stream resolution (lower values reduce latency).
- `camera_stream.port`: camera stream TCP port.
- `camera_stream.host_client`: Pi IP used by PC viewer if `--host` is not passed.
- `camera_stream.client_hflip`: horizontal flip in PC viewer.
- `camera_stream.client_vflip`: vertical flip in PC viewer.
- `camera_stream.client_display_width/height`: resize output window frame on PC viewer.
- `servo_control.pi_host/pi_port`: PC UI target for camera servo command UDP.
- `servo_control.listen_host/listen_port`: Pi servo server bind address and port.
- `servo_control.pan_channel/tilt_channel`: servo channels used for camera mount.
- `servo_control.step`: angle step per arrow button press.
- `servo_control.invert_tilt`: reverse up/down direction in PC arrow UI.
- `servo_control.home_pan/home_tilt`: home angle when pressing Home button (or `H` key).

## Camera servo arrow UI

When running PC master mode, `Client/camera_servo_ui.py` opens a small arrow-button window:
- Up/Down: tilt servo
- Left/Right: pan servo
- Home button (or keyboard `H`): return to configured home angles
- Arrow keys also work when the window is focused

## Quest 3 DIY FPV (first working version)

1. Start Pi with Quest FPV mode:

```bash
python3 master_control.py --role pi --config g29_control/config.json --quest-fpv
```

2. On Quest browser, open:

```text
http://<PI_IP>:8080
```

3. In the page:
- Video appears from `/stream.mjpg`
- Manual pan/tilt buttons work immediately
- Prefer **Start XR Tracking** on Quest 3 (inline XR mode, no immersive scene load)
- `Enable Gyro Tracking` remains as fallback for browsers exposing `DeviceOrientation`
- Tap **Recenter** while looking forward

Config keys:
- `quest_fpv.host`, `quest_fpv.port`
- `quest_fpv.https_enabled`, `quest_fpv.https_port`
- `quest_fpv.tls_cert_path`, `quest_fpv.tls_key_path`
- `quest_fpv.http_redirect_to_https`
- `quest_fpv.pan_channel`, `quest_fpv.tilt_channel`
- `quest_fpv.home_pan`, `quest_fpv.home_tilt`
- `quest_fpv.yaw_to_deg`, `quest_fpv.pitch_to_deg`
- `quest_fpv.invert_tilt`
- `quest_fpv.video_rotate_180` (Quest page-only 180-degree video rotation)
- `quest_fpv.xr_prefer_immersive` (`true` uses immersive XR; FPV video is rendered into XR layer)
- `quest_fpv.immersive_square_frame` (`true` renders a centered square frame in immersive mode)
- `quest_fpv.immersive_frame_scale` (0.2..1.0, size of square immersive frame)

### Native HTTPS setup for Quest sensors

On Pi, generate a self-signed cert:

```bash
chmod +x scripts/generate_quest_tls.sh
./scripts/generate_quest_tls.sh
```

Then set in `g29_control/config.json`:

```json
"https_enabled": true,
"https_port": 8443
```

Run Quest FPV server, then open:

```text
https://<PI_IP>:8443
```

If enabled, HTTP port can auto-redirect to HTTPS using `http_redirect_to_https`.

## Tuning checklist

1. Lift wheels off the ground and verify direction first.
2. Start with low `mapping.max_pwm` (for example, 1400).
3. Increase `mapping.max_pwm` gradually.
4. Tune `mapping.steer_gain` (0.5-1.0 typical).
5. Validate packet-loss behavior by turning off sender; car must stop quickly.
6. Validate deadman and e-stop before floor driving.
