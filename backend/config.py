from pathlib import Path, PurePosixPath

from pydantic_settings import BaseSettings, SettingsConfigDict

# Mount point for the host data directory inside Docker containers.
# Host ``data/`` is mounted read-write here for all Docker-based operations
# (terrain downloads, solver execution).  This is a structural invariant of
# the Docker setup, not a per-environment setting.
CONTAINER_DATA_ROOT = PurePosixPath("/data")


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
    solver_timeout_seconds: int = 600
    solver_max_retries: int = 2
    solver_mesh_resolution: float = 100.0
    # Uniform vegetation for DEM-based griddedInitialization.
    # TODO(Phase 4+): Add LCP-aligned grid support for per-pixel vegetation.
    solver_vegetation: str = "trees"
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
