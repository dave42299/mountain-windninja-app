"""Enums shared across ORM models and Pydantic schemas.

In a separate module so that importing enums does not pull in the ORM layer,
database engine, or any other heavyweight dependencies. This allows Pydantic
schemas, CLI tools, and tests to use the enums without a live database.
"""

import enum


class ForecastStatus(str, enum.Enum):
    queued = "queued"
    fetching_weather = "fetching_weather"
    running_solver = "running_solver"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class WeatherModel(str, enum.Enum):
    hrrr = "hrrr"
    nbm = "nbm"


class SolverType(str, enum.Enum):
    mass_conservation = "mass_conservation"
    momentum = "momentum"
