"""Run the app locally: ``python -m sba``."""

import uvicorn

from sba.config import settings


def main() -> None:
    uvicorn.run("sba.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
