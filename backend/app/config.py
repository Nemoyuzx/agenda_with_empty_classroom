from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo


APP_TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_TERM_ID = os.getenv("DEFAULT_TERM_ID", "2025-2026-2")
DEFAULT_TERM_START_DATE = os.getenv("DEFAULT_TERM_START_DATE", "2026-03-02")

JWGL_HOME_URL = "https://jwgl.bupt.edu.cn/jsxsd/"
JWGL_LOGIN_URL = "https://jwgl.bupt.edu.cn/jsxsd/xk/LoginToXk"
JWGL_TIMETABLE_URL = "https://jwgl.bupt.edu.cn/jsxsd/xskb/xskb_print.do"

SJD_LOGIN_PAGE_URL = "http://jwglweixin.bupt.edu.cn/sjd/#/login"
SJD_REST_CLASSROOM_PAGE_URL = "http://jwglweixin.bupt.edu.cn/sjd/#/restClassroom"
SJD_API_BASE_URL = os.getenv("SJD_API_BASE_URL", "http://jwglweixin.bupt.edu.cn/bjyddx").rstrip("/")
EMPTY_CLASSROOM_LOGIN_URL = f"{SJD_API_BASE_URL}/login"
EMPTY_CLASSROOM_QUERY_URL = f"{SJD_API_BASE_URL}/todayClassrooms"


@dataclass(frozen=True)
class Campus:
    id: str
    name: str


CAMPUSES = [
    Campus(id="01", name="西土城"),
    Campus(id="04", name="沙河"),
]

SLOT_TIMES = [
    ("08:00", "08:45"),
    ("08:50", "09:35"),
    ("09:50", "10:35"),
    ("10:40", "11:25"),
    ("11:30", "12:15"),
    ("13:00", "13:45"),
    ("13:50", "14:35"),
    ("14:45", "15:30"),
    ("15:40", "16:25"),
    ("16:35", "17:20"),
    ("17:25", "18:10"),
    ("18:30", "19:15"),
    ("19:20", "20:05"),
    ("20:10", "20:55"),
]


def campus_name(campus_id: str) -> str:
    normalized = normalize_campus_id(campus_id)
    for campus in CAMPUSES:
        if campus.id == normalized:
            return campus.name
    return f"校区 {normalized}"


def normalize_campus_id(campus_id: str | int | None) -> str:
    if campus_id is None:
        return CAMPUSES[0].id
    value = str(campus_id).strip()
    if value.isdigit():
        return value.zfill(2)
    return value


def today_in_app_tz() -> date:
    return datetime.now(APP_TZ).date()


def slot_payload() -> list[dict[str, str | int]]:
    return [
        {"index": index, "label": f"{index + 1}", "start": start, "end": end}
        for index, (start, end) in enumerate(SLOT_TIMES)
    ]
