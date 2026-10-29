"""Load user settings from config.toml."""

import dataclasses
import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.toml"
MIN_POLL_INTERVAL_MINUTES = 1
PLACEHOLDER_MEMBER_NAME = "CHANGE_ME"


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Settings read from config.toml.

    :ivar memberName: First name of the Family Safety member to monitor.
    :ivar pollIntervalMinutes: Minutes between Family Safety checks.
    :ivar alertThresholdsMinutes: Minutes-left values that trigger a notification,
        highest first and without duplicates.
    """

    memberName: str
    pollIntervalMinutes: float = 5
    alertThresholdsMinutes: tuple[int, ...] = (240, 180, 120, 30)

    @classmethod
    def fromFile(cls, path: Path = DEFAULT_CONFIG_PATH) -> "Config":
        """Read the configuration file. A poll interval below the minimum is raised to it.

        :param path: Location of the TOML configuration file.
        :return: The parsed configuration.
        :raises ConfigError: If the file cannot be read, has unknown or missing
            settings, has a setting of the wrong type, or memberName is still the
            placeholder.
        """
        try:
            with path.open("rb") as file:
                data = tomllib.load(file)
        except (OSError, tomllib.TOMLDecodeError) as err:
            raise ConfigError(f"Could not read {path}: {err}") from err

        _checkTypes(data, path)
        
        if "alertThresholdsMinutes" in data:
            data["alertThresholdsMinutes"] = tuple(sorted(set(data["alertThresholdsMinutes"]), reverse=True))

        try:
            config = cls(**data)
        except TypeError as err:
            raise ConfigError(f"Invalid settings in {path}: {err}") from err

        if config.memberName == PLACEHOLDER_MEMBER_NAME:
            raise ConfigError(f"Set memberName in {path} to the family member's first name.")

        if config.pollIntervalMinutes < MIN_POLL_INTERVAL_MINUTES:
            _LOGGER.warning(
                f"pollIntervalMinutes is {config.pollIntervalMinutes}; defaulting to {MIN_POLL_INTERVAL_MINUTES}."
            )
            config = dataclasses.replace(config, pollIntervalMinutes=MIN_POLL_INTERVAL_MINUTES)

        return config


def _isNumber(value: object) -> bool:
    """Check whether a TOML value is an integer or float (TOML booleans don't count).

    :param value: The value to check.
    :return: True if the value is an int or float but not a bool.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _checkTypes(data: dict, path: Path) -> None:
    """Check that each setting in the raw TOML data has the expected type.

    :param data: Settings as parsed from the TOML file.
    :param path: Location of the file, for error messages.
    :raises ConfigError: If a setting has the wrong type.
    """
    if "memberName" in data and not isinstance(data["memberName"], str):
        raise ConfigError(f'memberName in {path} must be quoted text, e.g. "Alex".')
    
    if "pollIntervalMinutes" in data and not _isNumber(data["pollIntervalMinutes"]):
        raise ConfigError(f"pollIntervalMinutes in {path} must be a number.")
    
    if "alertThresholdsMinutes" in data:
        thresholds = data["alertThresholdsMinutes"]
        isIntegerList = isinstance(thresholds, list)
        if isIntegerList:
            for threshold in thresholds:
                if not isinstance(threshold, int) or isinstance(threshold, bool):
                    isIntegerList = False
        if not isIntegerList:
            raise ConfigError(
                f"alertThresholdsMinutes in {path} must be a list of whole minutes, e.g. [240, 180, 120, 30]."
            )
