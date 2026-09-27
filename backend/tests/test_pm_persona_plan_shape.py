"""Regression test for bug #34 (car-search plan missing detail-extraction stages): the PM
persona's system prompt must explicitly require browser_navigate/browser_extract_text stages
after any web_search stage in a comparison/shopping-style task, so a persona-authored plan never
jumps straight from search snippets to QA/widget without opening and reading real candidates.
"""
from mainforte.personas.catalog import get


def test_pm_prompt_requires_detail_extraction_after_web_search():
    pm = get("pm")
    prompt = pm.system_prompt

    assert "web_search" in prompt
    assert "browser_navigate" in prompt
    assert "browser_extract_text" in prompt

    # The guidance must tie web_search to the follow-up extraction stages, not just mention
    # both tools somewhere unrelated.
    web_search_idx = prompt.index("web_search")
    browser_navigate_idx = prompt.index("browser_navigate")
    assert web_search_idx < browser_navigate_idx
