from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .config import DEFAULT_TERM_ID, DEFAULT_TERM_START_DATE


def default_term_start_date() -> date:
    return date.fromisoformat(DEFAULT_TERM_START_DATE)


class Credentials(BaseModel):
    account: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=1)


class ScheduleRequest(Credentials):
    term_id: str = DEFAULT_TERM_ID
    term_start_date: date = Field(default_factory=default_term_start_date)


class ClassroomsRequest(Credentials):
    campus_id: str = "01"
    target_date: date | None = None


class RecommendationRequest(ScheduleRequest):
    campus_id: str = "01"
    target_date: date | None = None
    selected_slots: list[int] | None = None
    buildings: list[str] = Field(default_factory=list)
    min_seats: int = 0
    use_schedule_filter: bool = True


class Course(BaseModel):
    id: str
    name: str
    teacher: str = ""
    room: str = ""
    week_text: str = ""
    week_numbers: list[int] = Field(default_factory=list)
    weekday: int
    start_slot: int
    end_slot: int
    section_text: str = ""
    time_range: str = ""


class ScheduleResponse(BaseModel):
    term_id: str
    term_start_date: date
    fetched_at: datetime
    courses: list[Course]


class ClassroomStatus(BaseModel):
    id: str
    building: str
    room: str
    name: str
    size: int | None = None
    type: str = ""
    available_slots: list[int] = Field(default_factory=list)
    source: Literal["jwglweixin", "jray_public"] = "jwglweixin"


class ClassroomsResponse(BaseModel):
    campus_id: str
    campus_name: str
    target_date: date
    fetched_at: datetime
    realtime: bool = True
    provider: Literal["jwglweixin", "jray_public"] = "jwglweixin"
    rooms: list[ClassroomStatus]


class DateScheduleState(BaseModel):
    target_date: date
    week_number: int
    weekday: int
    busy_slots: list[int]
    free_slots: list[int]
    courses: list[Course]


class StayRange(BaseModel):
    start_slot: int
    end_slot: int
    length: int
    start_time: str
    end_time: str


class RoomRecommendation(BaseModel):
    classroom: ClassroomStatus
    matched_slots: list[int]
    ranges: list[StayRange]
    longest_range: StayRange | None
    fits_selected_slots: bool
    score: float


class RecommendationResponse(BaseModel):
    schedule: DateScheduleState
    classrooms: ClassroomsResponse
    selected_slots: list[int]
    recommendations: list[RoomRecommendation]


class MetadataResponse(BaseModel):
    campuses: list[dict[str, str]]
    slots: list[dict[str, str | int]]
    default_term_id: str
    default_term_start_date: str
