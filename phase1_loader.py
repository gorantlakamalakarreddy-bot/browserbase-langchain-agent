"""
Phase 1 — Basic Browserbase document loader.
Validates credentials and confirms baseline text extraction before the full agent.
Run:  python phase1_loader.py
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

for _var in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"):
    if not os.getenv(_var):
        raise EnvironmentError(f"Missing required environment variable: {_var}")

from langchain_community.document_loaders import BrowserbaseLoader


def load_pages(urls: list[str], text_only: bool = True):
    """Load one or more URLs via Browserbase and return LangChain Documents."""
    loader = BrowserbaseLoader(
        urls=urls,
        text_content=text_only,  # True = plain text, False = raw HTML
    )
    return loader.load()


if __name__ == "__main__":
    target = "https://example.com"
    print(f"Loading {target} via BrowserbaseLoader...")
    docs = load_pages([target])
    for doc in docs:
        print(f"\n--- {doc.metadata.get('source', target)} ---")
        print(doc.page_content[:800])
    print("\n[Phase 1 OK]")
