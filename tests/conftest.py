"""Fixtures for the Owlet tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest

from . import NOW, FakeCloud


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the custom integration in every test."""


@pytest.fixture(autouse=True)
def frozen_now(freezer) -> None:
    """Run every test ten seconds after the fixture vitals were recorded."""
    freezer.move_to(NOW)


@pytest.fixture(autouse=True)
def cloud() -> Generator[FakeCloud]:
    """Replace the HTTP session with a fake Owlet cloud, in every test."""
    fake = FakeCloud()
    with (
        patch("custom_components.owlet.async_get_clientsession", return_value=fake),
        patch(
            "custom_components.owlet.config_flow.async_get_clientsession",
            return_value=fake,
        ),
    ):
        yield fake
