"""TARS Core MVP Application Entrypoint for local development."""

import uvicorn

from tars.main import app

__all__ = ["app"]

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
