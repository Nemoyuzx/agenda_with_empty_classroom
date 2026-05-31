from __future__ import annotations

import hashlib
import re
from datetime import datetime

import httpx
import xlrd

from ..config import (
    APP_TZ,
    JWGL_HOME_URL,
    JWGL_LOGIN_URL,
    JWGL_TIMETABLE_URL,
    SLOT_TIMES,
)
from ..errors import BuptServiceError
from ..models import Course, ScheduleResponse
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


async def fetch_schedule(account: str | None, password: str | None, term_id: str, term_start_date) -> ScheduleResponse:
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
