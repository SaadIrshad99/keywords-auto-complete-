"""Minimal environment configuration for the backend foundation."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"


settings = Settings(app_env=os.getenv("APP_ENV", "development"))
