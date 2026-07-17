"""Pytest collection safety gates for opt-in OpenAI integration coverage."""

from __future__ import annotations

import os

import pytest


_INTEGRATION_MARKER = "openai_integration"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-openai-integration",
        action="store_true",
        default=False,
        help="run cost-acknowledged OpenAI Responses integration tests",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "openai_integration: real, cost-acknowledged OpenAI Responses integration coverage (triple-gated)",
    )


def _live_gate_reason(config: pytest.Config) -> str | None:
    if not config.getoption("--run-openai-integration"):
        return "requires --run-openai-integration"
    if os.getenv("RUN_OPENAI_INTEGRATION") != "1":
        return "requires RUN_OPENAI_INTEGRATION=1"
    if os.getenv("OPENAI_INTEGRATION_COST_ACK") != "YES":
        return "requires OPENAI_INTEGRATION_COST_ACK=YES"
    if os.getenv("CI") and os.getenv("OPENAI_INTEGRATION_TRUSTED_RUNNER") != "1":
        return "refuses untrusted CI; requires OPENAI_INTEGRATION_TRUSTED_RUNNER=1"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    reason = _live_gate_reason(config)
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if item.get_closest_marker(_INTEGRATION_MARKER):
            item.add_marker(skip)
