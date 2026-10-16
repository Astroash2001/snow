"""Real gateway probe with stored keys. Skipped by default (`network`)."""

import json

import pytest

from snow.brain.config import ModelsConfig
from snow.brain.probe import probe
from snow.config.secrets import KNOWN_KEYS, get_secret
from snow.config.settings import load_config

pytestmark = pytest.mark.network


async def test_live_probe_lists_models_for_every_keyed_provider() -> None:
    if not any(get_secret(k.name) for k in KNOWN_KEYS if k.name != "cartesia"):
        pytest.skip("no provider key stored")
    report = await probe(load_config("models.toml", ModelsConfig))
    for name, info in report["providers"].items():
        if info["status"] != "skipped: no key":
            assert info["models"] > 0, f"{name}: {info['status']}"
    assert "fake-" not in json.dumps(report)
