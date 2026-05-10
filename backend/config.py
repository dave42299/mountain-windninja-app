from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    database_url: str = "postgresql://windninja:windninja@localhost:5432/windninja"
    data_dir: Path = Path("./data")
    solver_image: str = "mountain-windninja:local"
    solver_threads: int = 4
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
