from __future__ import annotations

import os

import uvicorn

from voice2.api import create_app

app = create_app()


def run() -> None:
    uvicorn.run(
        "voice2.main:app",
        host=os.getenv("VOICE2_HOST", "127.0.0.1"),
        port=int(os.getenv("VOICE2_PORT", "8765")),
        reload=False,
    )


if __name__ == "__main__":
    run()

