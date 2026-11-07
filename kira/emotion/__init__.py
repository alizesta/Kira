"""Kira emotion & reaction system.

Layers (each can change without touching the others):
  1. emotion_library/emotions.json   WHAT Kira feels (ids, priority, intensity, duration, ...)
  2. emotion_library/reactions.json  HOW it is expressed (technology independent face + gesture names)
  3. emotion_library/animation/*.json HOW a given avatar technology performs a gesture (PNG soft-body today)
  4. emotion_library/avatar/profile.json WHICH assets / capabilities the active avatar has

  library.py      loads + validates the JSON (never executes anything from it)
  engine.py       priority, conflicts, blending, smoothing, anti-jitter (pure Python, no Qt)
  parser.py       reads the emotion tag the model writes, kept apart from the visible text
  director.py     glue used by the application: events, replies, TTS state, prompt hint
  backend_png.py  the only Qt-aware file: drives the existing FaceAnimator / Rig
"""
