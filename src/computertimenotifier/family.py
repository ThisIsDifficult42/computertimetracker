"""Microsoft Family Safety access: login, token storage and remaining computer time."""

import logging
from datetime import datetime, timedelta
from typing import Self
from urllib.parse import urlencode

import aiohttp
import keyring
from pyfamilysafety import Account, Authenticator, FamilySafety
from pyfamilysafety.authenticator.const import CLIENT_ID, REDIRECT_URL, SCOPE
from pyfamilysafety.enum import DayOfWeek
from pyfamilysafety.exceptions import Unauthorized

_LOGGER = logging.getLogger(__name__)

KEYRING_SERVICE = "computertimenotifier"
KEYRING_USERNAME = "family-safety-refresh-token"
# The schedules API names the Windows platform "Windows" (not the library's "Desktop").
WINDOWS_SCHEDULE_NAME = "Windows"

LOGIN_URL = "https://login.live.com/oauth20_authorize.srf?" + urlencode(
    {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URL,
        "scope": SCOPE,
    }
)


class SetupError(Exception):
    """A problem the user must fix, such as an expired login; retrying will not help."""


def windowsTimeLeft(account: Account) -> timedelta | None:
    """Calculate how much Windows time the member has left today.

    :param account: A family member account populated by FamilySafety.update().
    :return: The remaining time (never negative), or None if no Windows limit is set today.
    """
    schedules = account.get_schedule()
    if schedules is None:
        _LOGGER.warning(f"Family Safety returned no schedules for {account.first_name}")
        return None

    # The library keys schedules and days by the raw API strings, e.g. "Windows" and "monday".
    windowsSchedule = schedules.get(WINDOWS_SCHEDULE_NAME)
    if windowsSchedule is None:
        _LOGGER.info(f"No Windows schedule for {account.first_name}; schedules found: {list(schedules.keys())}")
        return None

    dayName = str(list(DayOfWeek)[datetime.now().weekday()])
    restriction = windowsSchedule.daily_restrictions.get(dayName)
    if restriction is None:
        _LOGGER.info(
            f"No Windows limit for {account.first_name} on {dayName}; "
            f"days with limits: {list(windowsSchedule.daily_restrictions.keys())}"
        )
        return None

    # Sum today's usage across the account's Windows devices.
    usedMs = 0
    if account.devices is not None:
        for device in account.devices:
            isWindows = device.os_name is not None and "windows" in device.os_name.lower()
            _LOGGER.debug(
                f"Device {device.device_name}: os_name={device.os_name}, today_time_used={device.today_time_used} ms"
            )
            if isWindows and device.today_time_used is not None:
                usedMs += device.today_time_used
                _LOGGER.debug(f"usedMs increased to {usedMs}")

    remaining = timedelta(milliseconds=restriction.allowance - usedMs)
    return max(timedelta(0), remaining)


def _saveRefreshToken(token: str) -> None:
    """Store the refresh token in Windows Credential Manager.

    :param token: The Microsoft refresh token to store.
    """
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)


async def login(redirectUrl: str) -> None:
    """Exchange the browser redirect URL for a refresh token and store it.

    :param redirectUrl: The full oauth20_desktop.srf URL, including its "code" parameter.
    :raises ValueError: If the URL does not contain a code.
    :raises pyfamilysafety.exceptions.Unauthorized: If Microsoft rejects the code.
    """
    async with aiohttp.ClientSession() as session:
        auth = await Authenticator.create(token=redirectUrl, client_session=session)
    _saveRefreshToken(auth.refresh_token)


class FamilySafetyClient:
    """Holds a Family Safety session and reports a member's remaining Windows time.

    Use as an async context manager so the HTTP session is closed. The connection is made
    on the first query, so a network failure at startup can be retried by the caller.
    """

    def __init__(self, memberName: str) -> None:
        """Create a client.

        :param memberName: First name of the family member to report on (case-insensitive).
        """
        self._memberName = memberName
        self._session: aiohttp.ClientSession | None = None
        self._auth: Authenticator | None = None
        self._family: FamilySafety | None = None
        self._savedToken: str | None = None

    async def __aenter__(self) -> Self:
        """Open the HTTP session.

        :return: This client.
        """
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *excInfo: object) -> None:
        """Close the HTTP session.

        :param excInfo: Exception details, if the block raised; not used.
        """
        await self._session.close()

    async def getTimeLeft(self) -> timedelta | None:
        """Fetch the latest data from Family Safety and calculate the time left.

        :return: The member's remaining Windows time today, or None if no limit is set today.
        :raises SetupError: If not logged in, the login has expired, or the member is not
            found.
        """

        # Only connect if we haven't connected before (_family is empty), otherwise update.
        if self._family is None:
            await self._connect()
        try:
            await self._family.update()
        except Unauthorized as err:
            raise SetupError("Family Safety login has expired. Run the login command.") from err

        self._saveRotatedToken()
        return windowsTimeLeft(self._findMember())

    async def _connect(self) -> None:
        """Log in with the stored refresh token.

        :raises SetupError: If no token is stored or Microsoft rejects it.
        """
        token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if token is None:
            raise SetupError("Not logged in to Family Safety. Run the login command.")

        self._savedToken = token
        self._auth = await Authenticator.create(token=token, use_refresh_token=True, client_session=self._session)

        # A rejected refresh token leaves the authenticator without an expiry instead of raising.
        if self._auth.expires is None:
            raise SetupError("Family Safety login was rejected. Run the login command.")
        self._family = FamilySafety(self._auth)

    def _saveRotatedToken(self) -> None:
        """Store the refresh token again if Microsoft issued a new one."""
        if self._auth.refresh_token != self._savedToken:
            _LOGGER.debug("Saving rotated refresh token")
            _saveRefreshToken(self._auth.refresh_token)
            self._savedToken = self._auth.refresh_token

    def _findMember(self) -> Account:
        """Find the configured member among the family's accounts.

        :return: The matching account.
        :raises SetupError: If no account, or more than one, has the configured first name.
        """
        wantedName = self._memberName.casefold()
        matches = []
        for account in self._family.accounts:
            if account.first_name is not None and account.first_name.casefold() == wantedName:
                matches.append(account)
        if len(matches) != 1:
            raise SetupError(
                f"Expected one Family Safety member named {self._memberName!r}, "
                f"found {len(matches)}. Check memberName in config.toml."
            )
        return matches[0]
