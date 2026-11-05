"""Doubling wait between polls that find no work, reset when work arrives."""


class AdaptiveBackoff:
    """A wait that doubles on each idle poll, up to a cap, and resets on activity.

    The wait starts at ``base``. Each ``on_idle()`` doubles it, never past
    ``cap``. Each ``on_activity()`` or ``reset()`` sets it back to ``base``.

    A wait of zero cannot double, so with ``base`` 0 the wait stays 0 unless
    ``start`` is given: the first idle poll then sets the wait to ``start``, and
    later idle polls double it from there.

    A ``cap`` below ``base`` is raised to ``base``, so the wait never grows. The
    caller decides whether to warn about such a cap.
    """

    def __init__(self, base: float, cap: float, start: float | None = None) -> None:
        self._base = float(base)
        self._cap = max(float(cap), self._base)
        self._start = start
        self.current: float = self._base

    @property
    def base(self) -> float:
        """The wait after activity, and before the first idle poll."""
        return self._base

    @property
    def cap(self) -> float:
        """The longest wait. Never below ``base``."""
        return self._cap

    def on_idle(self) -> float:
        """Grow the wait after a poll that found no work, and return it."""
        if self.current == 0:
            grown = float(self._start) if self._start is not None else 0.0
        else:
            grown = self.current * 2
        self.current = min(grown, self._cap)
        return self.current

    def on_activity(self) -> float:
        """Reset the wait after a poll that found work, and return it."""
        return self.reset()

    def reset(self) -> float:
        """Set the wait back to ``base``, and return it."""
        self.current = self._base
        return self.current
