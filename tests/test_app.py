"""Tests for computertimenotifier.app, with the Family Safety client, toasts and sleep mocked."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from computertimenotifier.app import main, monitor
from computertimenotifier.config import Config
from computertimenotifier.family import SetupError


class StopLoop(Exception):
    """Raised by the mocked sleep to end the otherwise endless polling loop."""


def makeClient(readings: list) -> MagicMock:
    """Create a stand-in for FamilySafetyClient.

    :param readings: Successive results (or exceptions) of getTimeLeft().
    :return: The fake client, usable as an async context manager.
    """
    client = MagicMock()
    client.__aenter__.return_value = client
    client.getTimeLeft = AsyncMock(side_effect=readings)
    return client


async def runMonitor(readings: list) -> tuple[MagicMock, AsyncMock]:
    """Run monitor() over the given readings, stopping after the last one.

    :param readings: Successive results (or exceptions) of getTimeLeft().
    :return: The mocked showToast function and the mocked sleep function.
    """
    # monitor() sleeps after every reading. The fake sleep returns normally after each
    # reading except the last, where it raises StopLoop to break out of the endless loop.
    sleepResults = []
    for _ in range(len(readings) - 1):
        sleepResults.append(None)
    sleepResults.append(StopLoop())

    fakeClient = makeClient(readings)
    with (
        patch("computertimenotifier.app.FamilySafetyClient", return_value=fakeClient),
        patch("computertimenotifier.app.showToast") as fakeShowToast,
        patch("computertimenotifier.app.asyncio.sleep", side_effect=sleepResults) as fakeSleep,
        # StopLoop is how the run ends, so it is expected rather than a failure.
        pytest.raises(StopLoop),
    ):
        await monitor(Config("Alex", pollIntervalMinutes=5))
    return fakeShowToast, fakeSleep


async def testMonitorNotifiesAndKeepsPollingAfterErrors() -> None:
    fakeShowToast, fakeSleep = await runMonitor(
        [
            timedelta(hours=4, minutes=20),
            RuntimeError("network down"),
            timedelta(hours=3, minutes=59),
        ]
    )
    assert fakeShowToast.call_args_list == [
        call("You have 4:20 of computer time left today."),
        call("You have 4 hours of computer time left today."),
    ]
    assert fakeSleep.call_args_list == [call(300)] * 3


async def testMonitorShowsRepeatedErrorsAfterSilentRetries() -> None:
    error = RuntimeError("network down")
    fakeShowToast, _ = await runMonitor([error, error, error, timedelta(hours=1), error, error, error, error, error])
    assert fakeShowToast.call_args_list == [
        call("You have 1:00 of computer time left today."),
        call("Could not check Family Safety: network down"),
        call("Could not check Family Safety: network down"),
    ]


async def testMonitorStopsOnSetupError() -> None:
    client = makeClient([SetupError("Not logged in")])
    with (
        patch("computertimenotifier.app.FamilySafetyClient", return_value=client),
        pytest.raises(SetupError),
    ):
        await monitor(Config("Alex"))


@pytest.fixture
def noLogFile() -> MagicMock:
    """Stop main() from configuring logging, so tests don't write computertimenotifier.log.

    :return: The mocked logging setup function.
    """
    with patch("computertimenotifier.app._setUpLogging") as fakeSetUp:
        yield fakeSetUp


@pytest.mark.usefixtures("noLogFile")
def testMainReportsConfigErrors(tmp_path: Path) -> None:
    with patch("computertimenotifier.app.showToast") as fakeShowToast:
        exitCode = main(["--config", str(tmp_path / "missing.toml")])
    assert exitCode == 1
    fakeShowToast.assert_called_once()
    assert "Could not read" in fakeShowToast.call_args.args[0]


@pytest.mark.usefixtures("noLogFile")
def testMainLoginStoresToken() -> None:
    redirectUrl = "https://login.live.com/oauth20_desktop.srf?code=abc"
    with (
        patch("builtins.input", return_value=redirectUrl),
        patch("computertimenotifier.app.login", new_callable=AsyncMock) as fakeLogin,
    ):
        exitCode = main(["login"])
    assert exitCode == 0
    fakeLogin.assert_awaited_once_with(redirectUrl)
