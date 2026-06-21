# AYANEO Konkr Fit (HX470) — controller notes

Reference for the Konkr Fit's controller hardware and how HHD maps it. Keep
this in sync if the firmware or mappings change.

## Identification

- DMI `product_name` = `KONKR FIT` (matched in `const.py` → `CONFS`).
- Konkr is an AYANEO sub-brand; the controller hardware is the **same as the
  AYANEO 3**:
  - `1c4f:0002` — AYANEO COMPOSITE DEVICE (`AYA_VID`/`AYA_PID`). Carries the
    extra buttons and the right-side system buttons as keyboard keys.
  - `045e:028e` — Xbox-style gamepad (`GAMEPAD_VID`/`GAMEPAD_PID`). Carries the
    sticks, triggers, ABXY, d-pad, and the three left-side system buttons.
- Unlike the AYANEO 3 it has **no detachable modules** (no `ayaneo-ec` EC
  sysfs interface), so `magic_modules` is off.

## Physical button layout

Six "system / face" buttons surround the screen, plus four extra buttons
(two rear paddles + two LC/RC buttons). Looking at the device face-on:

```
   LEFT module                         RIGHT module
   [ left-top    ]                     [ right-top        ]
   [ L-sel ][ L-start ]                [ konkr ][ R-bottom ]
```

- **LC / RC**  = the two inner buttons under each grip.
- **rear-left / rear-right** = the two back paddles.

## Raw evdev codes (captured on-device)

| # | Physical button       | Device           | Sends (evdev)            |
|---|-----------------------|------------------|--------------------------|
| 1 | left-top              | gamepad (028e)   | `BTN_MODE` (316)         |
| 2 | left-bottom-left      | gamepad (028e)   | `BTN_SELECT` (314)       |
| 3 | left-bottom-right     | gamepad (028e)   | `BTN_START` (315)        |
| 4 | right-top             | composite (0002) | `Ctrl` (29) + `F23` (193)|
| 5 | konkr (right-btm-left)| composite (0002) | `F23` (193) alone        |
| 6 | right-bottom-right    | composite (0002) | `Meta` (125) + `D` (32)  |
| - | LC                    | composite (0002) | `F21` (191)              |
| - | RC                    | composite (0002) | `F22` (192)              |
| - | rear-left paddle      | composite (0002) | `KEY_L` (38)             |
| - | rear-right paddle     | composite (0002) | `KEY_R` (19)             |

> **Important gotcha:** right-top (#4) and konkr (#5) emit the **same** key
> (`F23`). right-top just also holds `Ctrl`. A plain one-code → one-action map
> can't tell them apart — see the chord handling below.

## How HHD maps them

### Extra buttons (LC/RC + rear paddles)
`extra_buttons: "quad"`. These map to `extra_l1/l2/r1/r2` and are exposed as
DualSense Edge / Xbox Elite back paddles — remappable in **Steam Input**:

| Button     | evdev   | Output     |
|------------|---------|------------|
| rear-left  | `KEY_L` | `extra_l1` |
| rear-right | `KEY_R` | `extra_r1` |
| LC         | `F21`   | `extra_l2` |
| RC         | `F22`   | `extra_r2` |

### The six system/face buttons — "Konkr Button Map"
Enabled by the `face_remap` flag in `const.py`. Each button gets a dropdown
(`konkr_buttons.yml`, injected in `__init__.py:settings()`), applied in
`base.py`. Trimmed option set: `mode` (Steam/Guide), `share` (Quick Access
Menu / overlay), `select`, `start`, `disabled`.

| Dropdown key       | Physical button   | Source code    | Default    |
|--------------------|-------------------|----------------|------------|
| `btn_left_top`     | left-top          | `BTN_MODE`     | `mode`     |
| `btn_left_select`  | left-bottom-left  | `BTN_SELECT`   | `select`   |
| `btn_left_start`   | left-bottom-right | `BTN_START`    | `start`    |
| `btn_right_top`    | right-top         | `Ctrl`+`F23`   | `disabled` |
| `btn_konkr`        | konkr             | `F23`          | `disabled` |
| `btn_right_bottom` | right-bottom-right| `KEY_D`        | `share`    |

- Left-side three go through the gamepad: `base.py` overrides
  `XBOX_BUTTON_MAP` for `BTN_MODE/SELECT/START`; `disabled` drops the key.
- Right-side three go through the composite keyboard:
  - `KEY_D` → `btn_right_bottom`.
  - `F23` is split by **`ChordGamepadEvdev`** (`evdev.py`): if `Ctrl` is held
    it resolves to `btn_right_top`, otherwise `btn_konkr`. The action is
    **latched on press** so the release matches even if `Ctrl` is let go
    first (prevents stuck buttons).

Defaults reproduce the pre-remap behavior, so existing users see no change
until they touch a dropdown. Everything is gated on `face_remap`, so the
AYANEO 3's identical gamepad buttons are never affected.

## Files

- `const.py` — `CONFS["KONKR FIT"]` device entry + flags.
- `konkr_buttons.yml` — the six dropdowns (UI schema).
- `__init__.py` — injects the schema when `face_remap` is set.
- `base.py` — reads the dropdowns and builds the evdev button maps.
- `../../controller/physical/evdev.py` — `ChordGamepadEvdev`.
