"""TARS Package Main Entrypoint."""

import uvicorn

from tars.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("tars.main:app", host="0.0.0.0", port=8000, reload=True)
