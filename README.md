# Browserbase + LangChain Web Browsing Agent

AI-powered autonomous web research and interaction system.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env and fill in BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, OPENAI_API_KEY

# 3. Phase 1 — validate credentials with the basic loader
python phase1_loader.py

# 4. Smoke test cheap tools
python smoke_test.py

# 5. Smoke test including rendered_extract (spins up a real browser session)
python smoke_test.py --full

# 6. Run the full agent
python agent.py
```

## File layout

| File | Purpose |
|---|---|
| `phase1_loader.py` | Phase 1 — BrowserbaseLoader, validates credentials |
| `tools.py` | The four browser tools (search, fetch, rendered_extract, interactive_task) |
| `agent.py` | Phase 2 — main planner + subagent + approval loop |
| `smoke_test.py` | Independent tool tests |
| `.env.example` | Environment variable template |
| `requirements.txt` | Python dependencies |

## Tool cost ladder

| Tool | Cost | When to use |
|---|---|---|
| `browserbase_search` | Cheapest | No URL known — discover relevant pages |
| `browserbase_fetch` | Cheap | URL known, page is static HTML |
| `browserbase_rendered_extract` | Expensive | Page needs JavaScript to render |
| `browserbase_interactive_task` | Costliest | Must click, type, or submit — **requires approval** |

## Approval gate

Any call to `browserbase_interactive_task` pauses execution and prompts:

```
============================================================
  APPROVAL REQUIRED
============================================================
  Tool   : browserbase_interactive_task
  URL    : https://...
  Task   : Log in and extract the first API key
============================================================
  [A]pprove / [E]dit task / [R]eject  →
```

- **A** — execute as described
- **E** — modify the task description before executing
- **R** — cancel; the agent receives a rejection signal

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `BROWSERBASE_API_KEY` | Yes | From browserbase.com dashboard |
| `BROWSERBASE_PROJECT_ID` | Yes | From browserbase.com dashboard |
| `OPENAI_API_KEY` | Yes | Main planner LLM |
| `STAGEHAND_MODEL` | No | Override Stagehand extraction model |
| `STAGEHAND_AGENT_MODEL` | No | Override Stagehand interactive model |
| `DEEPAGENT_MODEL` | No | Override main planner model (default: gpt-4o) |
