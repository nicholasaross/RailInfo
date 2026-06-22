"""Tests for railinfo.config.load_settings env parsing."""

from __future__ import annotations

import pytest

from railinfo import config
from railinfo.config import ConfigError, load_settings

# Every env var load_settings looks at — cleared before each test for isolation.
_ALL_VARS = [
    "LDBWS_BASE_URL_LDB", "BWS_API_KEY_LDB",
    "LDBWS_BASE_URL_LADB", "BWS_API_KEY_LADB",
    "LDBWS_BASE_URL_LNDB", "BWS_API_KEY_LNDB",
    "LDBWS_BASE_URL_SD", "BWS_API_KEY_SD",
    "STATION_CRS", "FILTER_CRS_LIST", "LDBWS_TIME_OFFSET", "LDBWS_TIME_WINDOW",
    "PIXOO_HOST", "DIRECTION_FILTER_CRS", "DIRECTION_FILTER_TYPE",
]


@pytest.fixture
def env(monkeypatch):
    """Isolate from the real .env: stub load_dotenv and start from a clean slate with
    only the minimum required vars set. Tests add/override as needed."""
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LDBWS_BASE_URL_LDB", "http://example/{crs}")
    monkeypatch.setenv("BWS_API_KEY_LDB", "key")
    monkeypatch.setenv("STATION_CRS", "ELD")
    return monkeypatch


def test_direction_filter_parsed(env):
    env.setenv("DIRECTION_FILTER_CRS", "lbg")  # lower-case → normalised
    settings = load_settings()
    assert settings.direction_filter_crs == "LBG"
    assert settings.direction_filter_type == "to"  # default


def test_direction_filter_type_override(env):
    env.setenv("DIRECTION_FILTER_CRS", "VIC")
    env.setenv("DIRECTION_FILTER_TYPE", "From")  # case-insensitive
    assert load_settings().direction_filter_type == "from"


def test_no_direction_filter_by_default(env):
    settings = load_settings()
    assert settings.direction_filter_crs is None
    assert settings.direction_filter_type == "to"


def test_station_crs_required(env):
    env.delenv("STATION_CRS", raising=False)
    with pytest.raises(ConfigError):
        load_settings()


def test_ldb_endpoint_required(env):
    env.delenv("LDBWS_BASE_URL_LDB", raising=False)
    with pytest.raises(ConfigError):
        load_settings()


def test_station_crs_quotes_and_case_normalised(env):
    env.setenv("STATION_CRS", '"eld"')
    assert load_settings().station_crs == "ELD"
