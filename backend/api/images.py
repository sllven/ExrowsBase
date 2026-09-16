from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import UniversityImage, get_db
from api.universities import _serialize_image

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/{image_id}")
def get_image(image_id: str, db: Session = Depends(get_db)) -> dict:
    img = db.get(UniversityImage, image_id)
    if not img:
        raise HTTPException(404, "Image not found")
    data = _serialize_image(img)
    data["university_id"] = img.university_id
    data["university_name"] = img.university.canonical_name
    return data
