"""Decide which time-left notifications to show."""

from collections.abc import Iterable
from datetime import timedelta


def formatHoursMinutes(duration: timedelta) -> str:
    """Format a duration as H:MM, dropping any seconds.

    :param duration: The duration to format.
    :return: Hours and zero-padded minutes, e.g. "3:05".
    """
    totalMinutes = int(duration.total_seconds() // 60)
    hours, minutes = divmod(totalMinutes, 60)
    return f"{hours}:{minutes:02d}"


def _pluralize(count: int, unit: str) -> str:
    """Combine a count with its unit.

    :param count: How many of the unit.
    :param unit: The singular unit name, e.g. "hour".
    :return: Text such as "1 hour" or "2 hours".
    """
    if count == 1:
        return f"{count} {unit}"
    return f"{count} {unit}s"


def describeMinutes(minutes: int) -> str:
    """Describe a number of minutes in words.

    :param minutes: A non-negative number of minutes.
    :return: Text such as "2 hours", "30 minutes" or "1 hour 30 minutes".
    """
    hours, remainingMinutes = divmod(minutes, 60)
    parts = []
    if hours > 0:
        parts.append(_pluralize(hours, "hour"))
    if remainingMinutes > 0 or hours == 0:
        parts.append(_pluralize(remainingMinutes, "minute"))
    return " ".join(parts)


class AlertTracker:
    """Decides when to notify so that each threshold is announced only once.

    The first reading announces the exact time left. After that, a notification is shown
    when a threshold is newly passed; if several are passed between readings, only the
    lowest is announced. When more time becomes available (extra time is granted, or the
    allowance resets on a new day), thresholds above the new time left are re-armed.
    """

    def __init__(self, thresholdsMinutes: Iterable[int]) -> None:
        """Create a tracker.

        :param thresholdsMinutes: Minutes-left values that should trigger a notification.
        """
        self._thresholdsMinutes = set(thresholdsMinutes)
        self._started = False
        self._previousTimeLeft: timedelta | None = None
        self._passedThresholds: set[int] = set()

    def update(self, timeLeft: timedelta | None) -> str | None:
        """Record the latest time left and decide whether to notify.

        :param timeLeft: Computer time left today, or None if no limit applies today.
        :return: The notification text to show, or None if nothing should be shown.
        """
        if timeLeft is None:
            return None

        minutesLeft = timeLeft.total_seconds() / 60

        # If the time increased, we need to reset the passed thresholds
        if self._previousTimeLeft is not None and timeLeft > self._previousTimeLeft:
            # Keep only the thresholds still passed, so the others can be announced again.
            stillPassed = set()
            for threshold in self._passedThresholds:
                if minutesLeft <= threshold:
                    stillPassed.add(threshold)
            self._passedThresholds = stillPassed
        self._previousTimeLeft = timeLeft

        newlyPassed = set()
        for threshold in self._thresholdsMinutes:
            if minutesLeft <= threshold and threshold not in self._passedThresholds:
                newlyPassed.add(threshold)
        self._passedThresholds.update(newlyPassed)

        if not self._started:
            self._started = True
            amount = formatHoursMinutes(timeLeft)
        elif len(newlyPassed) > 0:
            amount = describeMinutes(min(newlyPassed))
        else:
            return None
        return f"You have {amount} of computer time left today."
