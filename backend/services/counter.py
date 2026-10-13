"""
Line-crossing counter.

Design (kept intentionally simple for a beginner-friendly project):
  - The counting line is horizontal, at a configurable fraction of the
    frame height (settings.counting_line_position).
  - For every tracked vehicle we remember which SIDE of the line its
    center point was on last frame ("above" or "below").
  - The moment a track's side flips, and that track ID has never been
    counted before, we count it exactly once and remember its ID
    forever (for the lifetime of this processing run) in `counted_ids`.

This guarantees a vehicle is never counted twice while its tracker ID
stays stable. If the tracker loses and re-acquires a vehicle (a new ID
is assigned to the same physical vehicle), that would show up as a
second crossing -- see `suspected_duplicates` below, a heuristic that
flags crossings which happen very close in time and space to an
already-counted crossing, so it can be reviewed during testing.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from backend.utils.config import VEHICLE_CLASS_KEYS


@dataclass
class CrossingEvent:
    track_id: int
    class_name: str
    x: float
    y: float
    t: float


class LineCounter:
    def __init__(self, line_y: float):
        self.line_y = line_y
        self.last_side: Dict[int, str] = {}       # track_id -> "above"/"below"
        self.counted_ids = set()
        self.counts = {k: 0 for k in VEHICLE_CLASS_KEYS}
        self.counts["total"] = 0
        self.recent_crossings = []  # list[CrossingEvent], for duplicate heuristic
        self.suspected_duplicates = 0

    def _side(self, y: float) -> str:
        return "above" if y < self.line_y else "below"

    def update(self, track_id: int, class_name: str, center: tuple, t: float) -> Optional[CrossingEvent]:
        """Feed one detection in. Returns a CrossingEvent if a NEW count
        just happened, otherwise None."""
        cx, cy = center
        side = self._side(cy)
        previous_side = self.last_side.get(track_id)
        self.last_side[track_id] = side

        if previous_side is None or previous_side == side:
            return None  # no crossing this frame

        if track_id in self.counted_ids:
            return None  # already counted this ID, ignore repeat crossings

        self.counted_ids.add(track_id)
        self.counts[class_name] = self.counts.get(class_name, 0) + 1
        self.counts["total"] += 1

        event = CrossingEvent(track_id=track_id, class_name=class_name,
                               x=cx, y=cy, t=t)
        self._flag_if_duplicate(event)
        self.recent_crossings.append(event)
        return event

    def _flag_if_duplicate(self, event: CrossingEvent):
        """Heuristic: a crossing that lands within 40px and 1.5s of a
        recent crossing of the same class is very likely the SAME
        physical vehicle re-acquired under a new track ID (a tracker
        ID switch), rather than a genuinely new vehicle. We don't
        auto-correct the count (that risks under-counting real
        vehicles), we just flag it for the tester to review."""
        for past in reversed(self.recent_crossings[-10:]):
            if past.class_name != event.class_name:
                continue
            if event.t - past.t > 1.5:
                break
            dist = ((event.x - past.x) ** 2 + (event.y - past.y) ** 2) ** 0.5
            if dist < 40:
                self.suspected_duplicates += 1
                return
