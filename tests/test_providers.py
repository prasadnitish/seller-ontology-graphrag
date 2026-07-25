from __future__ import annotations

import pytest

from graphkit.providers import PROFILES, check_profile, planner_for
from graphkit.retrieval import RulePlanner


@pytest.mark.asyncio
async def test_offline_profile_is_explicitly_preview_only() -> None:
    result = await check_profile(PROFILES["offline"])

    assert result["ready"] is True
    assert "preview only" in result["limitations"][0].lower()
    assert isinstance(planner_for(PROFILES["offline"]).planner, RulePlanner)


@pytest.mark.asyncio
async def test_openai_profile_reports_missing_key_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = await check_profile(PROFILES["openai"])

    assert result["ready"] is False
    assert result["reason"] == "OPENAI_API_KEY is not configured"
