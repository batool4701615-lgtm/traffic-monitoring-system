"""
Traffic density estimation.

Rule used (configurable on the Settings page):
  Look at how many vehicles crossed the counting line in the last
  `window_seconds` (a rolling window, default 30s) -- NOT the total
  count since the video started. This way density reflects the
  CURRENT flow of traffic instead of only ever climbing as the video
  plays.

    vehicles_in_window <= density_low_max      -> LOW
    <= density_medium_max                      -> MEDIUM
    above density_medium_max                   -> HIGH

The thresholds are counts-per-window, so they naturally scale with the
window length you choose. Documented here and in the README so it can
be justified in a project report.
"""

from collections import deque
from dataclasses import dataclass


@dataclass
class DensityResult:
    level: str
    vehicles_in_window: int
    window_seconds: int


class DensityCalculator:
    def __init__(self, window_seconds: int, low_max: int, medium_max: int):
        self.window_seconds = window_seconds
        self.low_max = low_max
        self.medium_max = medium_max
        self._events = deque()  # timestamps of crossings

    def add_event(self, t: float):
        self._events.append(t)

    def _prune(self, now: float):
        cutoff = now - self.window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def current(self, now: float) -> DensityResult:
        self._prune(now)
        count = len(self._events)
        if count <= self.low_max:
            level = "LOW"
        elif count <= self.medium_max:
            level = "MEDIUM"
        else:
            level = "HIGH"
        return DensityResult(level=level, vehicles_in_window=count,
                              window_seconds=self.window_seconds)
