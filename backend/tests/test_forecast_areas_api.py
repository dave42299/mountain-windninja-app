"""Tests for api.routers.forecast_areas -- CRUD endpoints via TestClient."""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.deps import get_db
from api.main import app
from tests.conftest import BERTHOUD_LAT, BERTHOUD_LON, BERTHOUD_SIZE_KM


@pytest.fixture
def client(db_session: Session):
    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


_VALID_BODY = {
    "center_latitude": BERTHOUD_LAT,
    "center_longitude": BERTHOUD_LON,
    "size_km": BERTHOUD_SIZE_KM,
    "label": "Berthoud Pass",
}


class TestCreateForecastArea:
    def test_valid_body_returns_201(self, client: TestClient) -> None:
        response = client.post("/forecast-areas/", json=_VALID_BODY)
        assert response.status_code == 201
        data = response.json()
        assert data["center_latitude"] == 39.80
        assert data["center_longitude"] == -105.77
        assert data["size_km"] == 10.0
        assert data["label"] == "Berthoud Pass"
        assert "id" in data
        assert "created_at" in data

    def test_default_size_km(self, client: TestClient) -> None:
        body = {"center_latitude": 40.0, "center_longitude": -105.0}
        response = client.post("/forecast-areas/", json=body)
        assert response.status_code == 201
        assert response.json()["size_km"] == 12

    def test_missing_latitude_returns_422(self, client: TestClient) -> None:
        body = {"center_longitude": -105.0, "size_km": 10.0}
        response = client.post("/forecast-areas/", json=body)
        assert response.status_code == 422

    def test_latitude_out_of_range_returns_422(self, client: TestClient) -> None:
        body = {"center_latitude": 95.0, "center_longitude": -105.0}
        response = client.post("/forecast-areas/", json=body)
        assert response.status_code == 422


class TestListForecastAreas:
    def test_empty_list(self, client: TestClient) -> None:
        response = client.get("/forecast-areas/")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_created_areas(self, client: TestClient) -> None:
        client.post("/forecast-areas/", json=_VALID_BODY)
        response = client.get("/forecast-areas/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["label"] == "Berthoud Pass"

    def test_ordered_by_created_at_descending(self, client: TestClient) -> None:
        first = {"center_latitude": 39.0, "center_longitude": -105.0, "label": "first"}
        client.post("/forecast-areas/", json=first)
        time.sleep(0.01)
        second = {"center_latitude": 40.0, "center_longitude": -106.0, "label": "second"}
        client.post("/forecast-areas/", json=second)

        response = client.get("/forecast-areas/")
        data = response.json()
        assert len(data) == 2
        assert data[0]["label"] == "second"
        assert data[1]["label"] == "first"


class TestGetForecastArea:
    def test_returns_area(self, client: TestClient) -> None:
        create_response = client.post("/forecast-areas/", json=_VALID_BODY)
        area_id = create_response.json()["id"]

        response = client.get(f"/forecast-areas/{area_id}")
        assert response.status_code == 200
        assert response.json()["id"] == area_id

    def test_not_found(self, client: TestClient) -> None:
        response = client.get(f"/forecast-areas/{uuid.uuid4()}")
        assert response.status_code == 404


class TestDeleteForecastArea:
    def test_delete_returns_204(self, client: TestClient) -> None:
        create_response = client.post("/forecast-areas/", json=_VALID_BODY)
        area_id = create_response.json()["id"]

        delete_response = client.delete(f"/forecast-areas/{area_id}")
        assert delete_response.status_code == 204

        get_response = client.get(f"/forecast-areas/{area_id}")
        assert get_response.status_code == 404

    def test_delete_not_found(self, client: TestClient) -> None:
        response = client.delete(f"/forecast-areas/{uuid.uuid4()}")
        assert response.status_code == 404
