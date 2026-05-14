"""
Entry point — starts the FastAPI server with hot reload.
Run:  python run.py
Then open:  http://localhost:8000
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import uvicorn

if __name__ == "__main__":
    print("Starting Browserbase Web Agent at http://localhost:8000")
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["src", "api"],
    )
