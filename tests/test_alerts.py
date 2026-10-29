"""Tests for computertimenotifier.alerts."""

from datetime import timedelta

import pytest

from computertimenotifier.alerts import AlertTracker, describeMinutes, formatHoursMinutes

THRESHOLDS = (240, 180, 120, 30)


def makeStartedTracker(timeLeft: timedelta) -> AlertTracker:
    """Create a tracker that has already handled its first reading.

    :param timeLeft: The first reading to give the tracker.
    :return: The tracker.
    """
    tracker = AlertTracker(THRESHOLDS)
    tracker.update(timeLeft)
    return tracker


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (timedelta(0), "0:00"),
        (timedelta(hours=3, minutes=5, seconds=59), "3:05"),
        (timedelta(hours=12), "12:00"),
    ],
)
def testFormatHoursMinutes(duration: timedelta, expected: str) -> None:
    assert formatHoursMinutes(duration) == expected


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "0 minutes"),
        (1, "1 minute"),
        (30, "30 minutes"),
        (60, "1 hour"),
        (120, "2 hours"),
        (90, "1 hour 30 minutes"),
    ],
)
def testDescribeMinutes(minutes: int, expected: str) -> None:
    assert describeMinutes(minutes) == expected


def testFirstReadingAnnouncesExactTimeLeft() -> None:
    tracker = AlertTracker(THRESHOLDS)
    message = tracker.update(timedelta(hours=1, minutes=45, seconds=20))
    assert message == "You have 1:45 of computer time left today."


def testFirstReadingWithNoLimitWaitsForALimit() -> None:
    tracker = AlertTracker(THRESHOLDS)
    assert tracker.update(None) is None
    assert tracker.update(timedelta(hours=2)) == "You have 2:00 of computer time left today."


def testCrossingAThresholdAnnouncesItOnce() -> None:
    tracker = makeStartedTracker(timedelta(hours=4, minutes=10))
    assert tracker.update(timedelta(hours=4, minutes=5)) is None
    assert tracker.update(timedelta(hours=4)) == "You have 4 hours of computer time left today."
    assert tracker.update(timedelta(hours=3, minutes=55)) is None


def testThresholdsPassedBeforeStartAreNotAnnounced() -> None:
    tracker = makeStartedTracker(timedelta(hours=2, minutes=30))
    assert tracker.update(timedelta(hours=2, minutes=1)) is None
    assert tracker.update(timedelta(hours=2)) == "You have 2 hours of computer time left today."


def testSeveralThresholdsPassedAtOnceAnnouncesOnlyTheLowest() -> None:
    tracker = makeStartedTracker(timedelta(hours=5))
    message = tracker.update(timedelta(hours=1, minutes=50))
    assert message == "You have 2 hours of computer time left today."


def testExtraTimeReArmsThresholds() -> None:
    tracker = makeStartedTracker(timedelta(minutes=25))
    assert tracker.update(timedelta(hours=1)) is None
    assert tracker.update(timedelta(minutes=30)) == "You have 30 minutes of computer time left today."


def testExtraTimeKeepsThresholdsStillPassed() -> None:
    tracker = makeStartedTracker(timedelta(minutes=20))
    assert tracker.update(timedelta(minutes=25)) is None
    assert tracker.update(timedelta(minutes=10)) is None
