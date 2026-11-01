"""Entry point kept for the launchers: `uvicorn app:app`. The application lives in the `mastervolt` package."""

from mastervolt.app import create_app

app = create_app()
