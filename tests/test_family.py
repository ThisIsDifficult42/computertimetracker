"""Tests for computertimenotifier.family, with keyring, aiohttp and pyfamilysafety mocked."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch

import pytest
from pyfamilysafety.enum import DayOfWeek
from pyfamilysafety.exceptions import Unauthorized
from pyfamilysafety.schedule import DailyRestriction, DeviceLimitsSchedule

from computertimenotifier.family import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    FamilySafetyClient,
    SetupError,
    login,
    windowsTimeLeft,
)

# Lowercase day names as the schedules API uses them, e.g. "monday".
TODAY = str(list(DayOfWeek)[datetime.now().weekday()])
TOMORROW = str(list(DayOfWeek)[(datetime.now().weekday() + 1) % 7])
MINUTE_MS = 60 * 1000


def makeDevice(osName: str | None, usedMinutes: int | None) -> SimpleNamespace:
    """Create a stand-in for a pyfamilysafety Device.

    :param osName: The device's operating system name.
    :param usedMinutes: Minutes used today, or None if not reported.
    :return: The fake device.
    """
    usedMs = None
    if usedMinutes is not None:
        usedMs = usedMinutes * MINUTE_MS
    return SimpleNamespace(device_name="Test device", os_name=osName, today_time_used=usedMs)


def makeAccount(
    schedules: dict | None,
    devices: list | None,
    firstName: str | None = "Alex",
) -> SimpleNamespace:
    """Create a stand-in for a pyfamilysafety Account.

    :param schedules: What get_schedule() returns, keyed by platform name.
    :param devices: The account's devices.
    :param firstName: The member's first name.
    :return: The fake account.
    """
    account = SimpleNamespace(first_name=firstName, devices=devices)
    account.get_schedule = lambda: schedules
    return account


def windowsSchedules(day: str, allowanceMinutes: int) -> dict:
    """Build a schedules dict, as the library returns it, with one Windows day limit.

    :param day: Lowercase day name, e.g. "monday".
    :param allowanceMinutes: The day's allowance in minutes.
    :return: Schedules keyed by platform name.
    """
    restrictions = {day: DailyRestriction.from_minutes(allowanceMinutes)}
    return {"Windows": DeviceLimitsSchedule("Windows", restrictions)}


def testTimeLeftSubtractsWindowsUsageOnly() -> None:
    account = makeAccount(
        windowsSchedules(TODAY, 180),
        [
            makeDevice("Windows", 20),
            makeDevice("Xbox", 100),
            makeDevice(None, 100),
            makeDevice("Windows", None),
        ],
    )
    assert windowsTimeLeft(account) == timedelta(minutes=160)


def testTimeLeftIsNeverNegative() -> None:
    account = makeAccount(windowsSchedules(TODAY, 60), [makeDevice("Windows", 90)])
    assert windowsTimeLeft(account) == timedelta(0)


def testTimeLeftWithoutDevicesIsWholeAllowance() -> None:
    account = makeAccount(windowsSchedules(TODAY, 60), None)
    assert windowsTimeLeft(account) == timedelta(minutes=60)


# Testing various "error" conditions for schedules
@pytest.mark.parametrize(
    "schedules",
    [
        None,
        {},
        {"Xbox": DeviceLimitsSchedule("Xbox", {TODAY: DailyRestriction.from_minutes(60)})},
        windowsSchedules(TOMORROW, 60),
    ],
)
def testTimeLeftIsNoneWithoutALimitForToday(schedules: dict | None) -> None:
    account = makeAccount(schedules, [makeDevice("Windows", 10)])
    assert windowsTimeLeft(account) is None


@pytest.fixture
def library() -> Iterator[dict[str, MagicMock]]:
    """Replace keyring, aiohttp and pyfamilysafety in the family module with mocks.

    The fake family contains one member, Alex, with 2 hours left today.

    :return: The mocks, keyed by the name they replace.
    """
    with patch.multiple(
        "computertimenotifier.family",
        keyring=DEFAULT,
        aiohttp=DEFAULT,
        Authenticator=DEFAULT,
        FamilySafety=DEFAULT,
    ) as mocks:
        mocks["aiohttp"].ClientSession.return_value.close = AsyncMock()
        mocks["keyring"].get_password.return_value = "stored-token"
        auth = SimpleNamespace(expires=object(), refresh_token="stored-token")
        mocks["Authenticator"].create = AsyncMock(return_value=auth)
        family = mocks["FamilySafety"].return_value
        family.update = AsyncMock()
        family.accounts = [
            makeAccount(windowsSchedules(TODAY, 180), [makeDevice("Windows", 60)]),
            makeAccount(None, None, firstName="Sam"),
            makeAccount(None, None, firstName=None),
        ]
        yield mocks


async def testGetTimeLeftForMember(library: dict[str, MagicMock]) -> None:
    async with FamilySafetyClient("alex") as client:
        assert await client.getTimeLeft() == timedelta(hours=2)
    library["Authenticator"].create.assert_awaited_once_with(
        token="stored-token",
        use_refresh_token=True,
        client_session=library["aiohttp"].ClientSession.return_value,
    )
    # Make sure we close the HTTP session
    library["aiohttp"].ClientSession.return_value.close.assert_awaited_once()


async def testConnectsOnlyOnce(library: dict[str, MagicMock]) -> None:
    async with FamilySafetyClient("Alex") as client:
        await client.getTimeLeft()
        await client.getTimeLeft()
    library["Authenticator"].create.assert_awaited_once()


async def testRotatedTokenIsSavedOnce(library: dict[str, MagicMock]) -> None:
    library["Authenticator"].create.return_value.refresh_token = "new-token"
    async with FamilySafetyClient("Alex") as client:
        await client.getTimeLeft()
        await client.getTimeLeft()
    library["keyring"].set_password.assert_called_once_with(KEYRING_SERVICE, KEYRING_USERNAME, "new-token")


async def testNotLoggedInRaisesSetupError(library: dict[str, MagicMock]) -> None:
    library["keyring"].get_password.return_value = None
    async with FamilySafetyClient("Alex") as client:
        with pytest.raises(SetupError, match="Not logged in"):
            await client.getTimeLeft()


async def testRejectedTokenRaisesSetupError(library: dict[str, MagicMock]) -> None:
    library["Authenticator"].create.return_value.expires = None
    async with FamilySafetyClient("Alex") as client:
        with pytest.raises(SetupError, match="rejected"):
            await client.getTimeLeft()


async def testExpiredLoginRaisesSetupError(library: dict[str, MagicMock]) -> None:
    library["FamilySafety"].return_value.update.side_effect = Unauthorized()
    async with FamilySafetyClient("Alex") as client:
        with pytest.raises(SetupError, match="expired"):
            await client.getTimeLeft()


async def testUnknownMemberRaisesSetupError(library: dict[str, MagicMock]) -> None:
    async with FamilySafetyClient("Jordan") as client:
        with pytest.raises(SetupError, match="found 0"):
            await client.getTimeLeft()


async def testLoginStoresRefreshToken(library: dict[str, MagicMock]) -> None:
    library["Authenticator"].create.return_value.refresh_token = "fresh-token"
    await login("https://login.live.com/oauth20_desktop.srf?code=abc")
    library["keyring"].set_password.assert_called_once_with(KEYRING_SERVICE, KEYRING_USERNAME, "fresh-token")
