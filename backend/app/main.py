from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import CAMPUSES, DEFAULT_TERM_ID, DEFAULT_TERM_START_DATE, slot_payload
from .errors import BuptServiceError
from .models import (
    ClassroomsRequest,
    ClassroomsResponse,
    MetadataResponse,
    RecommendationRequest,
    RecommendationResponse,
    ScheduleRequest,
    ScheduleResponse,
)
from .services.classrooms import fetch_classrooms
from .services.recommender import recommend
from .services.schedule import fetch_schedule

load_dotenv()

app = FastAPI(title="BUPT Agenda With Empty Classroom", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/metadata", response_model=MetadataResponse)
async def metadata() -> MetadataResponse:
    return MetadataResponse(
        campuses=[{"id": campus.id, "name": campus.name} for campus in CAMPUSES],
        slots=slot_payload(),
        default_term_id=DEFAULT_TERM_ID,
        default_term_start_date=DEFAULT_TERM_START_DATE,
    )


@app.post("/api/schedule", response_model=ScheduleResponse)
async def schedule(payload: ScheduleRequest) -> ScheduleResponse:
    try:
        return await fetch_schedule(payload.account, payload.password, payload.term_id, payload.term_start_date)
    except BuptServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/classrooms", response_model=ClassroomsResponse)
async def classrooms(payload: ClassroomsRequest) -> ClassroomsResponse:
    try:
        return await fetch_classrooms(payload.account, payload.password, payload.campus_id, payload.target_date)
    except BuptServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/recommendations", response_model=RecommendationResponse)
async def recommendations(payload: RecommendationRequest) -> RecommendationResponse:
    try:
        schedule_data = await fetch_schedule(
            payload.account,
            payload.password,
            payload.term_id,
            payload.term_start_date,
        )
        classroom_data = await fetch_classrooms(
            payload.account,
            payload.password,
            payload.campus_id,
            payload.target_date,
        )
        return recommend(
            courses=schedule_data.courses,
            term_start_date=schedule_data.term_start_date,
            classrooms=classroom_data,
            target_date=payload.target_date,
            selected_slots=payload.selected_slots,
            buildings=payload.buildings,
            min_seats=payload.min_seats,
            use_schedule_filter=payload.use_schedule_filter,
        )
    except BuptServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        target = frontend_dist / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(frontend_dist / "index.html")
