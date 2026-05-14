"""
Entry point — starts the FastAPI server.

Development (hot reload):
    python run.py --dev

Production:
    python run.py
    # or: uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Browserbase Web Agent server")
    parser.add_argument("--dev", action="store_true", help="Enable hot reload (development only)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    print(f"Starting Browserbase Web Agent at http://localhost:{args.port}")
    if args.dev:
        print("  Mode: development (hot reload ON)")
    else:
        print("  Mode: production")

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.dev,
        reload_dirs=["src", "api"] if args.dev else None,
        access_log=True,
    )


if __name__ == "__main__":
    main()
