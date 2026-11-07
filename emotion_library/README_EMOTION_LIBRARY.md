# Kira Emotion & Reaction Library

Data only (JSON). Nothing in this folder is executed, and nothing is downloaded automatically.
Library version: see `manifest.json` (`library_version`). Every file also carries `schema_version`
(currently `1`); files with an unsupported schema are skipped with a warning shown in the chat.

## The four layers

| Layer | File | Answers |
|---|---|---|
| Emotions | `emotions.json` | **What** Kira feels: id, name, category, aliases, meaning, default intensity (0-100), priority, duration, transition in/out, fallback, keywords |
| Reactions | `reactions.json` | **How** it is expressed, independent of avatar technology: face channels + a gesture name |
| Animation pack | `animation/png_softbody.json` | **How this avatar performs** a gesture: pose offsets, oscillating motion, one-shot pulses |
| Avatar profile | `avatar/profile.json` | **Which assets / capabilities** the avatar really has |

Also: `combinations.json` (conflicts, blends, replacements), `events.json` (app events -> reactions),
`rules.json` (stability numbers). Code lives in `kira/emotion/`; the engine never needs to change when
you edit these files.

## How the model tells Kira's avatar what she feels

The system prompt (built from this library) asks the model to start each reply with a tag on its own line:

    [smug:70]                 emotion id + intensity 0-100
    [shy+affectionate:55]     two emotions combined
    [happy]                   also accepted (intensity defaults to the emotion's default)

The tag is removed from the visible text and never shown or spoken. If the model writes no usable tag,
a weak keyword fallback (`keywords` in `emotions.json`) is tried; if that finds nothing, Kira's face simply
returns to idle. Kira's *character* is defined only in `kira/personality.py`; the hint only teaches the tag format.

## Adding things (no Python changes)

**A new emotion using an existing reaction** - append to `emotions.json`:

    {"id": "grumpy", "name": "Grumpy", "category": "personality", "aliases": ["cranky"],
     "meaning": "Bad mood, short answers.", "default_intensity": 50, "priority": 38, "duration": 7,
     "reaction": "irritation", "animation": {"png_softbody": "irritation"},
     "transition": {"in": 0.3, "out": 0.9}, "fallback": "annoyed",
     "keywords": {"fa": [], "en": ["grumpy"]}}

It automatically appears in the prompt's allowed list, is parsed from tags, and animates.

**A new reaction** - add to `reactions.json` (`face`: lid, raise, open, blush, smile; `gesture`: a name; `base_mood`:
one of neutral/happy/excited/sad/bored/angry/shy/surprised/thinking, which selects the rig's breathing/posture).

**A new gesture** - add to `animation/png_softbody.json` under `gestures`:
`pose` (static offsets), `motion` (sine oscillators: amp, freq Hz, phase), `onset` (name of a pulse played when
this emotion becomes dominant). Parts: head body chest skirt arm_l arm_r leg_l leg_r hair_l hair_r strap_l strap_r;
channels: ang (deg) tx ty (px) sc (scale). A missing gesture only means "face change, no body motion".

**A new combination** - `combinations.json`: `{"members": ["a","b"], "mode": "blend", "weights": [0.6,0.4]}`, or
`"mode": "replace", "result": "<emotion id>"`. Unlisted pairs blend by priority-weighted intensity. Add a pair to
`conflicts` to forbid showing two emotions together (the stronger wins).

**A new event reaction** - `events.json` (`emotion`, `intensity`, `duration`, `pulse`, `speaking`, `release_events`).
The application currently fires: app_startup, user_message, response_started, response_finished, response_failed,
tts_started, tts_stopped, user_interrupt.

**Drop-in packs** - any `*.json` in `packs/` (same keys as above: `emotions`, `reactions`, `combinations`, `events`,
`animation: {gestures, pulses}`) is merged at start-up. Existing ids are kept unless the entry has `"override": true`.
Packs are plain data; copy them in yourself - Kira never fetches art or code.

If something is wrong (bad JSON, missing reaction/gesture, duplicate id) Kira starts anyway, falls back to
`fallback` / neutral and lists the problem as a system message in the chat.

## Stability rules (`rules.json`)

* An automatic emotion cannot replace the current one for `min_hold_s` unless its priority is at least
  `preempt_priority_margin` higher; the newest request waits (`pending_ttl_s`) and is applied afterwards.
* More than `switch_budget.max_switches` switches in `window_s` doubles the hold.
* Same emotion again = refresh, not restart. Intensity scales face and motion; it fades during `transition.out`.
* While TTS audio plays, the reply's emotion does not expire. When nothing is active the avatar returns to the
  original idle behaviour.
* Max `max_blend` emotions at once; conflicting pairs cannot coexist.

## What the current PNG can and cannot do (honest limits)

`assets/kira_character.png` is **one flat image**. Today's avatar already had (before this task): a soft-body
puppet warp of body parts, and *procedurally painted* overlays for eyelids, cheek-raise, mouth and blush.
The emotion system only drives those. Therefore:

* Real: body posture/motion per emotion, eyelid/cheek/mouth/blush levels, speaking sway while audio plays.
* Not possible with this image: eyebrows, eye direction/pupil shape, hand-drawn expressions, tears, sweat
  drops, hearts. "Embarrassed", "jealous", "smug" are conveyed by blush, lids, smile and body language only.
  Combinations that need more than that fall back to the closest pose/blush mix; no expression is faked.
* Eyes/mouth cannot be separated from the flat PNG safely without new art, and no replacement art was generated.

## Future avatars (design only, nothing implemented beyond the PNG backend)

`avatar/profile.json` lists capabilities (`expression_images`, `eye_layers`, `mouth_layers`, `sprite_sequences`,
`live2d`, `vrm`), all `false` today. A reaction may declare `"requires": ["expression_images"]` and a `"fallback"`
reaction; it is used only when the profile says the capability exists (see `_example_image_smirk`).
A new backend in `kira/emotion/` only has to consume the engine's frame (`face`, `pose`, `base_mood`, `speaking`);
VRM expression presets and Live2D parameters map naturally onto the face channels. Needed assets, per goal:

* Several PNG expressions: one full-size PNG per reaction id, same canvas, transparent background.
* Eye/mouth layers: separate transparent PNGs (open/closed eyes, mouth shapes A-I-U-E-O) with anchor coordinates.
* GIF / sprite sequences: frame strips + fps per reaction.
* Live2D / VRM: the model files and a mapper from face channels to its parameters/expressions.
