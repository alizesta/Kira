"""Local, provider-neutral desktop perception primitives."""
from .active_window import ActiveWindowProbe
from .change_detector import ChangeDetector
from .engine import PerceptionEngine
from .events import PerceptionEvent

__all__ = ["ActiveWindowProbe", "ChangeDetector", "PerceptionEngine", "PerceptionEvent"]
