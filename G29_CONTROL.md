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

## Tuning checklist

1. Lift wheels off the ground and verify direction first.
2. Start with low `mapping.max_pwm` (for example, 1400).
3. Increase `mapping.max_pwm` gradually.
4. Tune `mapping.steer_gain` (0.5-1.0 typical).
5. Validate packet-loss behavior by turning off sender; car must stop quickly.
6. Validate deadman and e-stop before floor driving.
