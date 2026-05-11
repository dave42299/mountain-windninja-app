import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from models.orm import ForecastArea
from models.schemas import ForecastAreaCreate, ForecastAreaResponse

router = APIRouter(prefix="/forecast-areas", tags=["forecast-areas"])


@router.post("/", response_model=ForecastAreaResponse, status_code=201)
def create_forecast_area(
    body: ForecastAreaCreate,
    db: Session = Depends(get_db),
) -> ForecastArea:
    area = ForecastArea(
        center_latitude=body.center_latitude,
        center_longitude=body.center_longitude,
        size_km=body.size_km,
        label=body.label,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    return area


@router.get("/", response_model=list[ForecastAreaResponse])
def list_forecast_areas(
    db: Session = Depends(get_db),
) -> list[ForecastArea]:
    statement = select(ForecastArea).order_by(ForecastArea.created_at.desc())
    return list(db.scalars(statement).all())


@router.get("/{area_id}", response_model=ForecastAreaResponse)
def get_forecast_area(
    area_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ForecastArea:
    area = db.get(ForecastArea, area_id)
    if area is None:
        raise HTTPException(status_code=404, detail="Forecast area not found")
    return area


@router.delete("/{area_id}", status_code=204)
def delete_forecast_area(
    area_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    area = db.get(ForecastArea, area_id)
    if area is None:
        raise HTTPException(status_code=404, detail="Forecast area not found")
    db.delete(area)
    db.commit()
