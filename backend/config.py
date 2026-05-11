from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    database_url: str = "postgresql://windninja:windninja@localhost:5432/windninja"

    # Relative path resolves from CWD: in local dev (run from backend/),
    # this is backend/data/. In Docker (WORKDIR /app), this is /app/data/.
    data_dir: Path = Path("./data")

    solver_image: str = "mountain-windninja:local"
    # LANDFIRE LCP downloads via WindNinja ``fetch_dem`` can take many minutes.
    terrain_lcp_subprocess_timeout_seconds: int = 3600
    solver_threads: int = 4
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
