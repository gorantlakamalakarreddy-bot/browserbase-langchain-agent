"""
Smoke tests — verify each tool independently.
Run:  python smoke_test.py          (cheap tools only)
      python smoke_test.py --full   (includes Stagehand browser session)
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

for _var in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "OPENAI_API_KEY"):
    if not os.getenv(_var):
        print(f"[WARN] {_var} not set.", file=sys.stderr)

from tools import browserbase_fetch, browserbase_rendered_extract, browserbase_search


def _section(name: str) -> None:
    print(f"\n{'-' * 55}")
    print(f"  {name}")
    print("-" * 55)


def test_search() -> None:
    _section("browserbase_search — 'LangChain tutorial'")
    result = browserbase_search.invoke({"query": "LangChain tutorial", "num_results": 3})
    print(result)
    assert "http" in result.lower(), f"Expected URLs in results, got: {result[:100]}"
    print("[PASS]")


def test_fetch() -> None:
    _section("browserbase_fetch — https://example.com")
    result = browserbase_fetch.invoke({"url": "https://example.com"})
    print(result[:600])
    assert "[HTTP 200]" in result, f"Expected HTTP 200, got: {result[:100]}"
    print("[PASS]")


def test_rendered_extract() -> None:
    _section("browserbase_rendered_extract — https://quotes.toscrape.com/js/")
    result = browserbase_rendered_extract.invoke({
        "url": "https://quotes.toscrape.com/js/",
        "instruction": "Extract all quotes and their authors.",
    })
    print(result[:800])
    assert result.strip(), "Expected non-empty extraction result"
    print("[PASS]")


if __name__ == "__main__":
    run_full = "--full" in sys.argv
    tests = [test_search, test_fetch]
    if run_full:
        tests.append(test_rendered_extract)
        print("Running full suite (includes Stagehand browser session).")
    else:
        print("Running cheap-tool tests. Pass --full to include rendered_extract.")

    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as exc:
            print(f"[FAIL] {test.__name__}: {exc}")

    print(f"\nResult: {passed}/{len(tests)} passed.")
