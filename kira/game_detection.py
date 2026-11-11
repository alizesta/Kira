"""Pure foreground-window identity checks shared by Game Mode and portable tests."""
import re

_AI1_WINDOW_TITLE = re.compile(
    r"^(?:Project\s+)?Kira(?:\s+\d+(?:\.\d+)*)?(?:\s+stable)?$|^Ai1(?:\s+.*)?$",
    re.I,
)


def is_ai1_window(info, current_pid=None):
    """Return True for the current Ai1 process or one of its known product window titles."""
    info = info or {}
    if current_pid is not None:
        try:
            if int(info.get("pid", -1)) == int(current_pid):
                return True
        except (TypeError, ValueError):
            pass
    return bool(_AI1_WINDOW_TITLE.fullmatch(str(info.get("title") or "").strip()))
