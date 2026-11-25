# Kira UI Motion Foundation

## Scope

MotionManager is a general-purpose Qt animation foundation. It does not depend on the theme, colours, Glow, panels, avatar, chat, or Voice, and does not change the interface appearance by itself.

## Ownership and lifecycle

- One MotionManager is created per window, with that window as its parent.
- Animations use native Qt QPropertyAnimation and animation groups. No Python timer loop or per-frame calculations are added.
- Keyed animations stop the previous animation with the same key when a new one starts.
- Animations are removed from the Registry and released with `deleteLater` after completion or stop.
- All calls must run on the same Qt thread where the Manager was created.
- On the application's accepted exit path, shutdown stops all animations. A failed exit attempt does not shut the Manager down.

## API

- `animate`: animate one writable QObject property.
- `animate_group`: run multiple Property Tracks in parallel or sequence.
- `stop` and `stop_all`: cancel animations; with `finish=True`, apply the final value.
- `pause`, `resume`, `pause_all`, and `resume_all`: temporarily control animations.
- `active_count` and `active_keys`: inspect Registry state.

## Example

```python
from kira.ui.motion_manager import MotionManager, MotionTrack

motion = MotionManager(main_window)
motion.animate(
    panel,
    "maximumHeight",
    260,
    start_value=0,
    duration_ms=240,
    key="settings.panel",
)
motion.animate_group(
    (
        MotionTrack(panel, "minimumWidth", 360, start_value=320),
        MotionTrack(panel, "maximumWidth", 360, start_value=480),
    ),
    parallel=True,
    key="settings.panel.enter",
)
```

An animated property must be declared in the meta-object and writable, or exist as a dynamic property on the QObject.

## Outside this task

Connecting motion to tabs, panels, character behavior, colour palettes, Glass/Neon, and visual effects is future work. The current theme intentionally remains unchanged.
