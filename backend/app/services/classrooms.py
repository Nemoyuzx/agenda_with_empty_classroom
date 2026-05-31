from __future__ import annotations

import re
from datetime import date, datetime

import httpx

from ..config import (
    APP_TZ,
    EMPTY_CLASSROOM_LOGIN_URL,
    EMPTY_CLASSROOM_QUERY_URL,
    SJD_LOGIN_PAGE_URL,
    SJD_REST_CLASSROOM_PAGE_URL,
    campus_name,
    normalize_campus_id,
    today_in_app_tz,
)
from ..errors import BuptServiceError
from ..models import ClassroomStatus, ClassroomsResponse
from .credentials import resolve_credentials


SJD_ORIGIN = "http://jwglweixin.bupt.edu.cn"


def sjd_headers(token: str | None = None, referer: str = SJD_REST_CLASSROOM_PAGE_URL) -> dict[str, str]:
    headers = {
        "Origin": SJD_ORIGIN,
        "Referer": referer,
        "User-Agent": "Mozilla/5.0",
    }
    if token:
        headers["token"] = token
    return headers


def parse_classroom(raw: str) -> tuple[str, str, int | None] | None:
    clean = raw.strip()
    if not clean:
        return None

    size: int | None = None
    size_match = re.search(r"[\(（]\s*(\d+)\s*[\)）]", clean)
    if size_match:
        size = int(size_match.group(1))
        clean = clean[: size_match.start()].strip()

    clean = clean.replace("－", "-").replace("—", "-").replace("–", "-")
    if "-" in clean:
        building, room = clean.split("-", 1)
    else:
        building, room = "未知教学楼", clean
    building = building.strip() or "未知教学楼"
    room = room.strip() or clean
    return building, room, size


def parse_classrooms(raw: str) -> list[tuple[str, str, int | None]]:
    parsed: list[tuple[str, str, int | None]] = []
    for item in re.split(r"[,，;；]\s*", raw or ""):
        classroom = parse_classroom(item)
        if classroom is not None:
            parsed.append(classroom)
    return parsed


async def _login_empty_classroom(account: str, password: str) -> str:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            response = await client.post(
                EMPTY_CLASSROOM_LOGIN_URL,
                headers=sjd_headers(referer=SJD_LOGIN_PAGE_URL),
                data={
                    "userNo": account,
                    "pwd": password,
                    "encode": "1",
                    "captchaData": "",
                    "codeVal": "",
                },
            )
        except httpx.HTTPError as exc:
            raise BuptServiceError("无法连接空教室服务，请确认网络能访问 jwglweixin.bupt.edu.cn。") from exc

    if response.status_code >= 400:
        raise BuptServiceError(f"空教室服务登录失败，HTTP {response.status_code}。")

    try:
        payload = response.json()
    except ValueError as exc:
        raise BuptServiceError("空教室服务返回了无法识别的数据。") from exc

    if str(payload.get("code")) != "1":
        message = payload.get("Msg") or payload.get("msg") or "空教室服务登录失败。"
        raise BuptServiceError(str(message), 401)

    token = ((payload.get("data") or {}).get("token") or "").strip()
    if not token:
        raise BuptServiceError("空教室服务登录成功但没有返回 token。")
    return token


async def fetch_classrooms(
    account: str | None,
    password: str | None,
    campus_id: str | int | None,
    target_date: date | None = None,
) -> ClassroomsResponse:
    normalized_campus_id = normalize_campus_id(campus_id)
    service_date = today_in_app_tz()
    if target_date is not None and target_date != service_date:
        raise BuptServiceError("空教室实时服务目前只提供当天数据，请选择今天查询。", 400)

    user, secret = resolve_credentials(account, password)
    token = await _login_empty_classroom(user, secret)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            response = await client.post(
                EMPTY_CLASSROOM_QUERY_URL,
                params={"campusId": normalized_campus_id},
                headers=sjd_headers(token),
            )
        except httpx.HTTPError as exc:
            raise BuptServiceError("空教室数据获取失败，请稍后重试。") from exc

    if response.status_code >= 400:
        raise BuptServiceError(f"空教室数据获取失败，HTTP {response.status_code}。")
    try:
        payload = response.json()
    except ValueError as exc:
        raise BuptServiceError("空教室服务返回了无法识别的数据。") from exc

    if str(payload.get("code")) != "1":
        message = payload.get("Msg") or payload.get("msg") or "空教室数据获取失败。"
        raise BuptServiceError(str(message))

    room_map: dict[str, dict] = {}
    for item in payload.get("data") or []:
        try:
            slot = int(str(item.get("NODENAME") or item.get("nodeName"))) - 1
        except (TypeError, ValueError):
            continue
        if slot < 0 or slot >= 14:
            continue

        for building, room, size in parse_classrooms(str(item.get("CLASSROOMS") or "")):
            key = f"{building}-{room}"
            existing = room_map.setdefault(
                key,
                {
                    "id": key,
                    "building": building,
                    "room": room,
                    "name": key,
                    "size": size,
                    "type": "",
                    "available_slots": set(),
                },
            )
            if existing["size"] is None and size is not None:
                existing["size"] = size
            existing["available_slots"].add(slot)

    rooms = [
        ClassroomStatus(
            id=room["id"],
            building=room["building"],
            room=room["room"],
            name=room["name"],
            size=room["size"],
            type=room["type"],
            available_slots=sorted(room["available_slots"]),
        )
        for room in room_map.values()
    ]
    rooms.sort(key=lambda item: (item.building, item.room))
    return ClassroomsResponse(
        campus_id=normalized_campus_id,
        campus_name=campus_name(normalized_campus_id),
        target_date=service_date,
        fetched_at=datetime.now(APP_TZ),
        rooms=rooms,
    )
