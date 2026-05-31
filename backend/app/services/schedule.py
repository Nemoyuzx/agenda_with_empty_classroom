from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import xlrd

from ..config import (
    APP_TZ,
    JWGL_HOME_URL,
    JWGL_LOGIN_URL,
    JWGL_TIMETABLE_URL,
    SJD_STUDENT_CURRICULUM_URL,
    SLOT_TIMES,
)
from ..errors import BuptServiceError
from ..models import Course, ScheduleResponse
from .classrooms import _login_empty_classroom, sjd_headers
from .credentials import resolve_credentials

KEY_STR = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
DEFAULT_HEADERS = {
    "Host": "jwgl.bupt.edu.cn",
    "Referer": "https://jwgl.bupt.edu.cn/jsxsd/xk/LoginToXk?method=exit",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
}


def encode_inp(raw: str) -> str:
    output = ""
    index = 0
    while True:
        chr1 = ord(raw[index])
        index += 1
        chr2 = ord(raw[index]) if index < len(raw) else 0
        index += 1
        chr3 = ord(raw[index]) if index < len(raw) else 0
        index += 1
        enc1 = chr1 >> 2
        enc2 = ((chr1 & 3) << 4) | (chr2 >> 4)
        enc3 = ((chr2 & 15) << 2) | (chr3 >> 6)
        enc4 = chr3 & 63
        if chr2 == 0:
            enc3 = enc4 = 64
        elif chr3 == 0:
            enc4 = 64
        output += KEY_STR[enc1] + KEY_STR[enc2] + KEY_STR[enc3] + KEY_STR[enc4]
        if index >= len(raw):
            break
    return output


def encode_login(account: str, password: str) -> str:
    return f"{encode_inp(account)}%%%{encode_inp(password)}"


def expand_week_numbers(week_text: str) -> list[int]:
    raw = str(week_text).replace("，", ",").replace(" ", "")
    odd_only = "单" in raw
    even_only = "双" in raw
    raw = raw.replace("周", "")
    raw = re.sub(r"\[.*?\]", "", raw)
    raw = re.sub(r"\(.*?\)", "", raw)

    week_numbers: list[int] = []
    for item in raw.split(","):
        if not item:
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            if left.isdigit() and right.isdigit():
                week_numbers.extend(range(int(left), int(right) + 1))
        elif item.isdigit():
            week_numbers.append(int(item))

    unique_weeks = sorted(set(week_numbers))
    if odd_only:
        return [week for week in unique_weeks if week % 2 == 1]
    if even_only:
        return [week for week in unique_weeks if week % 2 == 0]
    return unique_weeks


def parse_cell_courses(cell_info: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in str(cell_info).splitlines() if line.strip()]
    courses: list[dict[str, str]] = []
    for index, line in enumerate(lines):
        if "[周]" not in line or not re.search(r"\d", line):
            continue
        if index + 2 >= len(lines):
            continue
        room = lines[index + 1]
        section = lines[index + 2]
        if "节" not in section:
            continue
        teacher = lines[index - 1] if index - 1 >= 0 else ""
        name_index = index - 2
        if name_index >= 0 and re.fullmatch(r"\(\d+\)", lines[name_index]):
            name_index -= 1
        if name_index < 0:
            continue
        courses.append(
            {
                "name": lines[name_index],
                "teacher": teacher,
                "week": line,
                "room": room,
                "section": section,
            }
        )
    return courses


def _slot_time_range(start_slot: int, end_slot: int) -> str:
    start = SLOT_TIMES[start_slot][0]
    end = SLOT_TIMES[end_slot][1]
    return f"{start}-{end}"


def parse_sjd_week_numbers(course: dict[str, Any]) -> list[int]:
    details = str(course.get("classWeekDetails") or "")
    weeks = [int(value) for value in re.findall(r"\d+", details)]
    if weeks:
        return sorted(set(weeks))
    return expand_week_numbers(str(course.get("classWeek") or ""))


def parse_sjd_slots(course: dict[str, Any]) -> tuple[int, int] | None:
    class_time = str(course.get("classTime") or "")
    nodes = [int(value) for value in re.findall(r"\d{2}", class_time[1:])]
    if not nodes:
        nodes = [int(value) for value in re.findall(r"\d+", str(course.get("weekNoteDetail") or ""))]
    if not nodes:
        return None
    start_slot = min(nodes) - 1
    end_slot = max(nodes) - 1
    if start_slot < 0 or end_slot >= len(SLOT_TIMES) or start_slot > end_slot:
        return None
    return start_slot, end_slot


def iter_sjd_course_items(raw_items: Any):
    if isinstance(raw_items, dict):
        if raw_items.get("courseName") or raw_items.get("jx0408id"):
            yield raw_items
            return
        for value in raw_items.values():
            yield from iter_sjd_course_items(value)
    elif isinstance(raw_items, list):
        for item in raw_items:
            yield from iter_sjd_course_items(item)


def parse_sjd_courses(payload: dict[str, Any], term_id: str, term_start_date: date) -> ScheduleResponse:
    data = payload.get("data") or []
    if not data:
        raise BuptServiceError("移动教务课表返回为空。")

    root = data[0]
    raw_items = root.get("item") or root.get("courses") or []
    courses: list[Course] = []
    seen_ids: set[str] = set()
    for raw_course in iter_sjd_course_items(raw_items):
        slots = parse_sjd_slots(raw_course)
        if slots is None:
            continue
        start_slot, end_slot = slots
        try:
            weekday = int(str(raw_course.get("weekDay") or str(raw_course.get("classTime") or "")[:1]))
        except ValueError:
            continue
        if weekday < 1 or weekday > 7:
            continue

        name = str(raw_course.get("courseName") or "未命名课程").strip()
        teacher = str(raw_course.get("teacherName") or "").strip()
        building = str(raw_course.get("buildingName") or "").strip()
        room = str(raw_course.get("classroomName") or raw_course.get("location") or "").strip()
        location = f"{building}-{room}" if building and room and building not in room else room or building
        week_text = str(raw_course.get("classWeek") or raw_course.get("classWeekDetails") or "").strip()
        week_numbers = parse_sjd_week_numbers(raw_course)
        stable = "|".join(
            [
                str(raw_course.get("jx0408id") or ""),
                name,
                teacher,
                location,
                week_text,
                str(weekday),
                str(start_slot),
                str(end_slot),
            ]
        )
        course_id = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12]
        if course_id in seen_ids:
            continue
        seen_ids.add(course_id)
        courses.append(
            Course(
                id=course_id,
                name=name,
                teacher=teacher,
                room=location,
                week_text=week_text,
                week_numbers=week_numbers,
                weekday=weekday,
                start_slot=start_slot,
                end_slot=end_slot,
                section_text=f"{start_slot + 1}-{end_slot + 1}节",
                time_range=str(raw_course.get("startTime") or SLOT_TIMES[start_slot][0])
                + "-"
                + str(raw_course.get("endTIme") or raw_course.get("endTime") or SLOT_TIMES[end_slot][1]),
            )
        )

    courses.sort(key=lambda item: (item.weekday, item.start_slot, item.name))
    return ScheduleResponse(
        term_id=term_id,
        term_start_date=term_start_date,
        fetched_at=datetime.now(APP_TZ),
        courses=courses,
    )


def infer_term_start_date(payload: dict[str, Any]) -> date | None:
    data = payload.get("data") or []
    if not data:
        return None
    root = data[0]
    try:
        week = int(str(root.get("week") or (root.get("topInfo") or [{}])[0].get("week")))
    except (TypeError, ValueError, IndexError):
        return None
    dates = root.get("date") or []
    dated = next((item for item in dates if item.get("mxrq") and str(item.get("zc")) != "all"), None)
    if not dated:
        return None
    try:
        day = date.fromisoformat(str(dated["mxrq"]))
        weekday = int(str(dated.get("xqid") or day.weekday() + 1))
    except (TypeError, ValueError):
        return None
    monday = day - timedelta(days=weekday - 1)
    return monday - timedelta(weeks=week - 1)


def parse_timetable_xls(content: bytes, term_id: str, term_start_date) -> ScheduleResponse:
    try:
        workbook = xlrd.open_workbook(file_contents=content)
    except Exception as exc:
        raise BuptServiceError("教务返回的课表文件无法解析，可能是登录失败或教务系统格式变化。") from exc

    sheet = workbook.sheet_by_index(0)
    max_row = min(sheet.nrows, 17)
    max_col = min(sheet.ncols, 8)
    courses: list[Course] = []
    seen_ids: set[str] = set()

    for column in range(1, max_col):
        weekday = column
        for row in range(3, max_row):
            cell_info = sheet.cell_value(rowx=row, colx=column)
            if not isinstance(cell_info, str) or not cell_info.strip():
                continue
            if row > 3 and cell_info == sheet.cell_value(rowx=row - 1, colx=column):
                continue

            end_row = row
            while end_row + 1 < max_row and sheet.cell_value(rowx=end_row + 1, colx=column) == cell_info:
                end_row += 1

            start_slot = row - 3
            end_slot = end_row - 3
            for parsed in parse_cell_courses(cell_info):
                week_numbers = expand_week_numbers(parsed["week"])
                stable = "|".join(
                    [
                        parsed["name"],
                        parsed["teacher"],
                        parsed["room"],
                        parsed["week"],
                        str(weekday),
                        str(start_slot),
                        str(end_slot),
                    ]
                )
                course_id = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12]
                if course_id in seen_ids:
                    continue
                seen_ids.add(course_id)
                courses.append(
                    Course(
                        id=course_id,
                        name=parsed["name"],
                        teacher=parsed["teacher"],
                        room=parsed["room"],
                        week_text=parsed["week"],
                        week_numbers=week_numbers,
                        weekday=weekday,
                        start_slot=start_slot,
                        end_slot=end_slot,
                        section_text=parsed["section"],
                        time_range=_slot_time_range(start_slot, end_slot),
                    )
                )

    courses.sort(key=lambda item: (item.weekday, item.start_slot, item.name))
    return ScheduleResponse(
        term_id=term_id,
        term_start_date=term_start_date,
        fetched_at=datetime.now(APP_TZ),
        courses=courses,
    )


async def fetch_sjd_schedule(account: str | None, password: str | None, term_id: str, fallback_term_start_date) -> ScheduleResponse:
    user, secret = resolve_credentials(account, password)
    token = await _login_empty_classroom(user, secret)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            current_response = await client.post(
                SJD_STUDENT_CURRICULUM_URL,
                params={"week": ""},
                headers=sjd_headers(token),
            )
            all_response = await client.post(
                SJD_STUDENT_CURRICULUM_URL,
                params={"week": "all"},
                headers=sjd_headers(token),
            )
        except httpx.HTTPError as exc:
            raise BuptServiceError("无法连接移动教务课表服务，请稍后重试。") from exc

    for response in (current_response, all_response):
        if response.status_code >= 400:
            raise BuptServiceError(f"移动教务课表获取失败，HTTP {response.status_code}。")

    try:
        current_payload = current_response.json()
        all_payload = all_response.json()
    except ValueError as exc:
        raise BuptServiceError("移动教务课表返回了无法识别的数据。") from exc

    if str(current_payload.get("code")) != "1":
        raise BuptServiceError(str(current_payload.get("Msg") or current_payload.get("msg") or "移动教务课表获取失败。"))
    if str(all_payload.get("code")) != "1":
        raise BuptServiceError(str(all_payload.get("Msg") or all_payload.get("msg") or "移动教务课表获取失败。"))

    inferred_start = infer_term_start_date(current_payload) or fallback_term_start_date
    inferred_term_id = str(
        ((current_payload.get("data") or [{}])[0].get("semesterId"))
        or ((current_payload.get("data") or [{}])[0].get("xnxq01id"))
        or term_id
    )
    return parse_sjd_courses(all_payload, inferred_term_id, inferred_start)


async def fetch_schedule_legacy(
    account: str | None,
    password: str | None,
    term_id: str,
    term_start_date,
) -> ScheduleResponse:
    user, secret = resolve_credentials(account, password)
    encoded = encode_login(user, secret)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            await client.get(JWGL_HOME_URL)
            login_response = await client.post(
                JWGL_LOGIN_URL,
                data={"userAccount": user, "userPassWord": "", "encoded": encoded},
                headers=DEFAULT_HEADERS,
            )
        except httpx.HTTPError as exc:
            raise BuptServiceError("无法连接新版教务系统，请确认网络能访问 jwgl.bupt.edu.cn。") from exc

        if login_response.status_code >= 400:
            raise BuptServiceError(f"新版教务登录失败，HTTP {login_response.status_code}。")

        params = {
            "xnxq01id": term_id,
            "zc": "",
            "kbjcmsid": "9475847A3F3033D1E05377B5030AA94D",
        }
        try:
            response = await client.post(JWGL_TIMETABLE_URL, params=params, data=params)
        except httpx.HTTPError as exc:
            raise BuptServiceError("无法获取课表打印文件，请稍后重试。") from exc

    content = response.content
    text_head = content[:500].decode("utf-8", errors="ignore").lower()
    if response.status_code >= 400 or "<html" in text_head or "login" in text_head:
        raise BuptServiceError("课表获取失败，请检查账号、密码、学期编号或校园网访问状态。", 401)
    if len(content) < 200:
        raise BuptServiceError("教务返回的课表内容为空。")
    return parse_timetable_xls(content, term_id, term_start_date)


async def fetch_schedule(account: str | None, password: str | None, term_id: str, term_start_date) -> ScheduleResponse:
    try:
        return await fetch_sjd_schedule(account, password, term_id, term_start_date)
    except BuptServiceError:
        return await fetch_schedule_legacy(account, password, term_id, term_start_date)
