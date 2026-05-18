"""Enums shared across ORM models and Pydantic schemas."""

import enum


class ForecastStatus(str, enum.Enum):
    queued = "queued"
    fetching_terrain = "fetching_terrain"
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
