from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="archived legacy pre-route routeing tests")


def test_pre_route_legacy_cases_archived_manifest() -> None:
    # Historical cases moved from tests/test_chat_route_outer_core_ws28_007.py:
    # - path-a/path-b/path-c pre-route classifier expectations
    # - pre-route clarify-budget escalation expectations
    # - pre-route router-arbiter ping-pong freeze expectations
    assert True
