"""Tests for computertimenotifier.config, with the configuration file mocked."""

from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from computertimenotifier.config import Config, ConfigError, _checkTypes

PATH = Path("config.toml")


def loadConfig(text: str) -> Config:
    """Load a configuration from TOML text, as if it had been read from config.toml.

    :param text: TOML content of the pretend file.
    :return: The loaded configuration.
    """
    with patch.object(Path, "open", mock_open(read_data=text.encode())):
        return Config.fromFile(PATH)


def testLoadsAllSettings() -> None:
    config = loadConfig('memberName = "Alex"\npollIntervalMinutes = 2\nalertThresholdsMinutes = [60, 10]\n')
    assert config == Config("Alex", 2, (60, 10))


def testUsesDefaultsForOptionalSettings() -> None:
    assert loadConfig('memberName = "Alex"\n') == Config("Alex", 5, (240, 180, 120, 30))


def testLoadingChecksTypes() -> None:
    with pytest.raises(ConfigError, match="memberName"):
        loadConfig("memberName = 123\n")


def testMissingFileRaisesConfigError() -> None:
    with (
        patch.object(Path, "open", side_effect=FileNotFoundError("No such file")),
        pytest.raises(ConfigError, match="Could not read"),
    ):
        Config.fromFile(PATH)


def testInvalidTomlRaisesConfigError() -> None:
    with pytest.raises(ConfigError, match="Could not read"):
        loadConfig("memberName = \n")


def testUnknownSettingRaisesConfigError() -> None:
    with pytest.raises(ConfigError, match="Invalid settings"):
        loadConfig('memberName = "Alex"\nmemberNmae = "typo"\n')


def testMissingMemberNameRaisesConfigError() -> None:
    with pytest.raises(ConfigError, match="Invalid settings"):
        loadConfig("pollIntervalMinutes = 5\n")


def testCorrectTypesPass() -> None:
    _checkTypes({"memberName": "Alex", "pollIntervalMinutes": 2.5, "alertThresholdsMinutes": [60, 10]}, PATH)


@pytest.mark.parametrize(
    ("data", "expectedMessage"),
    [
        ({"memberName": 123}, "memberName"),
        ({"pollIntervalMinutes": "5"}, "pollIntervalMinutes"),
        ({"alertThresholdsMinutes": 30}, "alertThresholdsMinutes"),
        ({"alertThresholdsMinutes": [60, "30"]}, "alertThresholdsMinutes"),
        ({"alertThresholdsMinutes": [60, 30.5]}, "alertThresholdsMinutes"),
    ],
)
def testWrongTypeRaisesConfigError(data: dict, expectedMessage: str) -> None:
    with pytest.raises(ConfigError, match=expectedMessage):
        _checkTypes(data, PATH)


def testPlaceholderMemberNameRaisesConfigError() -> None:
    with pytest.raises(ConfigError, match="Set memberName"):
        loadConfig('memberName = "CHANGE_ME"\n')


def testShortPollIntervalDefaultsToOneMinute(caplog: pytest.LogCaptureFixture) -> None:
    config = loadConfig('memberName = "Alex"\npollIntervalMinutes = 0.5\n')
    assert config.pollIntervalMinutes == 1
    assert "defaulting to 1" in caplog.text


def testThresholdsAreSortedHighestFirstWithoutDuplicates() -> None:
    config = loadConfig('memberName = "Alex"\nalertThresholdsMinutes = [30, 120, 30, 240]\n')
    assert config.alertThresholdsMinutes == (240, 120, 30)
