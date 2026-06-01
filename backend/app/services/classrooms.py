from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import httpx

from ..config import (
    APP_TZ,
    EMPTY_CLASSROOM_LOGIN_URL,
    EMPTY_CLASSROOM_TODAY_URL,
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
BUILDING_ALIASES = {
    "1": "教1",
    "2": "教2",
    "3": "教3",
    "4": "教4",
    "教一楼": "教1",
    "教二楼": "教2",
    "教三楼": "教3",
    "教四楼": "教4",
    "未来学习大楼": "主楼",
}


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
    parts = [part.strip() for part in clean.split("-") if part.strip()]
    if len(parts) >= 3 and parts[0] in {"校本部", "西土城", "沙河"}:
        room_start = clean.find(parts[2])
        building = clean[:room_start].rstrip("-").strip() if room_start >= 0 else parts[0]
        room = clean[room_start:].strip() if room_start >= 0 else "-".join(parts[1:])
    elif "-" in clean:
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


def normalize_building_name(name: str) -> str:
    clean = str(name or "").strip().replace("－", "-").replace("—", "-").replace("–", "-")
    clean = re.sub(r"^(校本部|西土城|沙河)-", "", clean)
    return BUILDING_ALIASES.get(clean, clean or "未知教学楼")


def original_building_name(name: str) -> bool:
    return name in {"教1", "教2", "教3", "教4", "主楼"}


def extract_room_name(room: str, building: str) -> str | None:
    clean = str(room or "").strip().replace("－", "-").replace("—", "-").replace("–", "-")
    if not clean:
        return None

    building_match = re.fullmatch(r"教([1-4])", building)
    if building_match:
        building_number = building_match.group(1)
        if clean.startswith(f"{building_number}-"):
            clean = clean.split("-", 1)[1].strip()
        elif clean.startswith(f"教{building_number}-"):
            clean = clean.split("-", 1)[1].strip()

    room_match = re.search(r"\d{3}(?:-\d{3})?", clean)
    return room_match.group(0) if room_match else None


def node_name_to_slot(value: str) -> int | None:
    match = re.search(r"\d+", str(value or "").strip())
    if not match:
        return None
    slot = int(match.group(0)) - 1
    return slot if 0 <= slot < 14 else None


async def _login_empty_classroom(account: str, password: str) -> str:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            response = await client.post(
                EMPTY_CLASSROOM_LOGIN_URL,
                headers=sjd_headers(referer=SJD_LOGIN_PAGE_URL),
                data={
                    "userNo": account,
                    "pwd": password,
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


def format_room_name(classroom: dict[str, Any]) -> str:
    room_number = str(classroom.get("classroomnumber") or classroom.get("classroomNumber") or "").strip()
    room_label = str(classroom.get("classroomname") or classroom.get("classroomName") or room_number).strip()
    return room_label or room_number or str(classroom.get("classroomId") or "未知教室")


def parse_idle_classroom_groups(groups: list[dict[str, Any]], slot: int, room_map: dict[str, dict]) -> None:
    for group in groups:
        building = normalize_building_name(str(
            group.get("teachingBuildingName")
            or group.get("buildingName")
            or group.get("teachingbuildingname")
            or "未知教学楼"
        ))
        if not building:
            building = "未知教学楼"
        if not original_building_name(building):
            continue

        for classroom in group.get("classroomList") or []:
            room = extract_room_name(format_room_name(classroom), building)
            if room is None:
                continue
            key = f"{building}-{room}"
            try:
                size = int(classroom.get("seatnumber") or classroom.get("seatNumber") or 0) or None
            except (TypeError, ValueError):
                size = None

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


def parse_today_classroom_items(items: list[dict[str, Any]], room_map: dict[str, dict]) -> None:
    for item in items:
        slot = node_name_to_slot(str(item.get("NODENAME") or item.get("nodeName") or item.get("nodename") or ""))
        if slot is None:
            continue

        for raw_building, room, size in parse_classrooms(
            str(item.get("CLASSROOMS") or item.get("classrooms") or "")
        ):
            building = normalize_building_name(raw_building)
            if not original_building_name(building):
                continue
            room = extract_room_name(room, building)
            if room is None:
                continue
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


async def _fetch_today_classrooms(
    client: httpx.AsyncClient,
    token: str,
    campus_id: str,
) -> list[dict[str, Any]]:
    try:
        response = await client.get(
            EMPTY_CLASSROOM_TODAY_URL,
            params={"campusId": campus_id},
            headers=sjd_headers(token),
        )
    except httpx.HTTPError as exc:
        raise BuptServiceError("今日空教室数据获取失败，请稍后重试。") from exc

    if response.status_code >= 400:
        raise BuptServiceError(f"今日空教室数据获取失败，HTTP {response.status_code}。")
    try:
        payload = response.json()
    except ValueError as exc:
        raise BuptServiceError("今日空教室服务返回了无法识别的数据。") from exc

    if str(payload.get("code")) != "1":
        message = payload.get("Msg") or payload.get("msg") or "今日空教室数据获取失败。"
        raise BuptServiceError(str(message))
    return payload.get("data") or []


async def fetch_classrooms(
    account: str | None,
    password: str | None,
    campus_id: str | int | None,
    target_date: date | None = None,
) -> ClassroomsResponse:
    normalized_campus_id = normalize_campus_id(campus_id)
    service_date = target_date or today_in_app_tz()
    if service_date != today_in_app_tz():
        raise BuptServiceError("空教室实时接口仅支持当天查询。", 400)

    user, secret = resolve_credentials(account, password)
    token = await _login_empty_classroom(user, secret)

    room_map: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        parse_today_classroom_items(
            await _fetch_today_classrooms(client, token, normalized_campus_id),
            room_map,
        )

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
