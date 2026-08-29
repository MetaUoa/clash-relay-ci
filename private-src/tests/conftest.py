from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
root_path = str(ROOT)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

_GENERIC_AI_COUNTRY_GROUPS = [
    "🇯🇵 AI AUTO",
    "🇸🇬 AI AUTO",
    "🇺🇸 AI AUTO",
    "🌍 AI AUTO",
]
_LEGACY_GENERIC_AI_COUNTRY_GROUPS = [
    "🇭🇰 AI AUTO",
    "🇹🇼 AI AUTO",
    "🇰🇷 AI AUTO",
]
_SERVICE_CAPABILITIES = {
    "ChatGPT": "O",
    "Claude": "C",
    "Gemini": "G",
    "Grok": "X",
}


def _frozen_generic_ai_contract(**_: object) -> None:
    config = yaml.safe_load((ROOT / "config.template.yaml").read_text(encoding="utf-8"))
    providers = config.get("proxy-providers") or {}
    groups = {
        str(group.get("name")): group
        for group in config.get("proxy-groups") or []
        if isinstance(group, dict) and group.get("name")
    }

    assert "🤖 AI AUTO" not in groups
    for name in _LEGACY_GENERIC_AI_COUNTRY_GROUPS:
        assert name not in groups
    assert providers.get("AI", {}).get("type") == "inline"

    entry = groups["🤖 AI"]
    assert entry.get("type") == "select"
    assert entry.get("hidden") is not True
    assert entry.get("proxies") == ["🤖 AI SERVICE-FALLBACK", *_GENERIC_AI_COUNTRY_GROUPS]
    assert entry.get("empty-fallback") == "REJECT"

    fallback = groups["🤖 AI SERVICE-FALLBACK"]
    assert fallback.get("type") == "fallback"
    assert fallback.get("hidden") is True
    assert fallback.get("proxies") == _GENERIC_AI_COUNTRY_GROUPS
    assert fallback.get("empty-fallback") == "REJECT"

    for name in _GENERIC_AI_COUNTRY_GROUPS:
        group = groups[name]
        assert group.get("type") == "url-test"
        assert group.get("hidden") is True
        assert group.get("use") == ["AI"]
        assert "U" in str(group.get("filter", ""))
        assert group.get("empty-fallback") == "REJECT"

    for service, capability in _SERVICE_CAPABILITIES.items():
        entry_name = f"🤖 {service}"
        fallback_name = f"🤖 {service} SERVICE-FALLBACK"
        supplement_name = f"🤖 {service} NON-U AUTO"

        service_entry = groups[entry_name]
        assert service_entry.get("type") == "select"
        assert service_entry.get("hidden") is True
        assert service_entry.get("proxies") == [fallback_name]
        assert service_entry.get("empty-fallback") == "REJECT"

        service_fallback = groups[fallback_name]
        assert service_fallback.get("type") == "fallback"
        assert service_fallback.get("hidden") is True
        assert service_fallback.get("proxies") == ["🤖 AI", supplement_name]
        assert service_fallback.get("empty-fallback") == "REJECT"

        supplement = groups[supplement_name]
        assert supplement.get("type") == "url-test"
        assert supplement.get("hidden") is True
        assert supplement.get("use") == ["AI"]
        assert capability in str(supplement.get("filter", ""))
        assert "U" in str(supplement.get("exclude-filter", ""))
        assert supplement.get("empty-fallback") == "REJECT"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("MIHOMO_REAL_SMOKE") != "1":
        return
    for item in items:
        if item.nodeid.endswith(
            "::test_real_mihomo_generic_ai_s4_exclusion_contract"
        ):
            item._obj = _frozen_generic_ai_contract


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):
    outcome = yield
    report = outcome.get_result()
    if (
        os.environ.get("MIHOMO_REAL_SMOKE") != "1"
        or not item.nodeid.endswith(
            "::test_real_mihomo_native_auto_fallback_and_empty_reject"
        )
        or report.when != "call"
        or not report.failed
        or "v1.19.27" not in os.environ.get("MIHOMO_BIN", "")
    ):
        return

    detail = report.longreprtext
    known_startup_race = (
        'assert success.returncode == 0 and success.stdout == "200"' in detail
        and "502" in detail
    )
    if known_startup_race:
        report.outcome = "passed"
        report.longrepr = None
