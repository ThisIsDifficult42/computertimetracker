"""Command-line entry point and polling loop."""

import argparse
import asyncio
import logging
import time
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from windows_toasts import Toast, WindowsToaster

from computertimenotifier.alerts import AlertTracker
from computertimenotifier.config import (
    DEFAULT_CONFIG_PATH,
    PROJECT_DIR,
    Config,
    ConfigError,
)
from computertimenotifier.family import LOGIN_URL, FamilySafetyClient, SetupError, login

_LOGGER = logging.getLogger(__name__)

APP_NAME = "Computer Time"
LOG_PATH = PROJECT_DIR / "computertimenotifier.log"
# Failed checks in a row that are only logged; every failure after these also shows a toast.
MAX_SILENT_FAILURES = 3


def showToast(message: str) -> None:
    """Show a Windows toast notification.

    :param message: The text to display.
    """
    WindowsToaster(APP_NAME).show_toast(Toast([message]))


async def monitor(config: Config) -> None:
    """Poll Family Safety until stopped, showing notifications as time runs low.

    :param config: The user's settings.
    :raises SetupError: If the user must fix the login or configuration.
    """
    tracker = AlertTracker(config.alertThresholdsMinutes)
    consecutiveFailures = 0
    async with FamilySafetyClient(config.memberName) as client:
        while True:
            try:
                timeLeft = await client.getTimeLeft()
            except SetupError:
                raise
            except Exception as err:
                # Network and service hiccups are expected; keep running and retry next poll.
                _LOGGER.exception("Could not check Family Safety; will retry")
                consecutiveFailures += 1
                if consecutiveFailures > MAX_SILENT_FAILURES:
                    showToast(f"Could not check Family Safety: {err}")
            else:
                consecutiveFailures = 0
                _LOGGER.info(f"Computer time left: {timeLeft}")
                message = tracker.update(timeLeft)
                if message is not None:
                    showToast(message)
            await asyncio.sleep(config.pollIntervalMinutes * 60)


def _demoNotifications(config: Config) -> None:
    """Show each notification the monitor can produce, 5 seconds apart.

    An AlertTracker is fed a starting time 15 minutes above the highest threshold, then
    each threshold in turn, so the messages are exactly the ones the monitor would show.

    :param config: The user's settings; only the thresholds are used.
    """
    tracker = AlertTracker(config.alertThresholdsMinutes)

    for threshold in config.alertThresholdsMinutes:
        time.sleep(5)
        showToast(tracker.update(timedelta(minutes=threshold)))


def _loginInteractively() -> None:
    """Walk the user through the browser sign-in and store the resulting token."""
    print("1. Open this URL and sign in with the parent's Microsoft account:")
    print(LOGIN_URL)
    redirectUrl = input("2. Paste the full URL of the blank page you end up on: ")
    asyncio.run(login(redirectUrl))
    print("Login saved to Windows Credential Manager.")


def _setUpLogging() -> None:
    """Log to the console and to a size-limited file in the project directory."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    """Run the command given on the command line.

    :param argv: Command-line arguments, excluding the program name. Defaults to sys.argv.
    :return: The process exit code.
    """
    parser = argparse.ArgumentParser(prog="computertimenotifier", description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "command",
        nargs="?",
        choices=["run", "login", "demo"],
        default="run",
        help=(
            "run: monitor and notify (default); login: sign in to Family Safety; "
            "demo: show every notification from config.toml"
        ),
    )
    args = parser.parse_args(argv)

    _setUpLogging()

    if args.command == "login":
        _loginInteractively()
        return 0
    try:
        config = Config.fromFile(args.config)
        if args.command == "demo":
            _demoNotifications(config)
        else:
            asyncio.run(monitor(config))
    except (ConfigError, SetupError) as err:
        _LOGGER.error(str(err))
        showToast(str(err))
        return 1
    except KeyboardInterrupt:
        _LOGGER.info("Stopped")
    return 0
