from __future__ import annotations

from datetime import date

from ..config import SLOT_TIMES, today_in_app_tz
from ..models import (
    ClassroomsResponse,
    Course,
    DateScheduleState,
    RecommendationResponse,
    RoomRecommendation,
    StayRange,
)

ALL_SLOTS = list(range(14))


def date_state(courses: list[Course], target_date: date, term_start_date: date) -> DateScheduleState:
    delta_days = (target_date - term_start_date).days
    week_number = delta_days // 7 + 1
    weekday = target_date.weekday() + 1

    day_courses = [
        course
        for course in courses
        if course.weekday == weekday and week_number in set(course.week_numbers)
    ]
    busy_slots = sorted(
        {
            slot
            for course in day_courses
            for slot in range(course.start_slot, course.end_slot + 1)
            if 0 <= slot < 14
        }
    )
    free_slots = [slot for slot in ALL_SLOTS if slot not in set(busy_slots)]
    return DateScheduleState(
        target_date=target_date,
        week_number=week_number,
        weekday=weekday,
        busy_slots=busy_slots,
        free_slots=free_slots,
        courses=sorted(day_courses, key=lambda item: (item.start_slot, item.name)),
    )


def compact_ranges(slots: list[int]) -> list[StayRange]:
    if not slots:
        return []
    sorted_slots = sorted(set(slots))
    ranges: list[StayRange] = []
    start = previous = sorted_slots[0]
    for slot in sorted_slots[1:]:
        if slot == previous + 1:
            previous = slot
            continue
        ranges.append(_make_range(start, previous))
        start = previous = slot
    ranges.append(_make_range(start, previous))
    return ranges


def _make_range(start_slot: int, end_slot: int) -> StayRange:
    return StayRange(
        start_slot=start_slot,
        end_slot=end_slot,
        length=end_slot - start_slot + 1,
        start_time=SLOT_TIMES[start_slot][0],
        end_time=SLOT_TIMES[end_slot][1],
    )


def recommend(
    courses: list[Course],
    term_start_date: date,
    classrooms: ClassroomsResponse,
    target_date: date | None,
    selected_slots: list[int] | None,
    buildings: list[str],
    min_seats: int,
    use_schedule_filter: bool = True,
) -> RecommendationResponse:
    date_to_check = target_date or today_in_app_tz()
    state = date_state(courses, date_to_check, term_start_date)
    schedule_allowed_slots = state.free_slots if use_schedule_filter else ALL_SLOTS
    valid_selected = sorted({slot for slot in selected_slots or [] if 0 <= slot < 14})
    source_slots = schedule_allowed_slots if selected_slots is None else valid_selected
    target_slots = [slot for slot in source_slots if slot in set(schedule_allowed_slots)]
    target_slot_set = set(target_slots)
    building_filter = {building for building in buildings if building}

    recommendations: list[RoomRecommendation] = []
    for room in classrooms.rooms:
        if building_filter and room.building not in building_filter:
            continue
        if room.size is not None and room.size < min_seats:
            continue

        available = set(room.available_slots)
        matched_slots = sorted(target_slot_set & available)
        if not matched_slots:
            continue

        fits_selected = bool(valid_selected) and set(valid_selected).issubset(set(matched_slots))
        if valid_selected and not fits_selected:
            continue

        ranges = compact_ranges(matched_slots)
        longest = max(ranges, key=lambda item: item.length, default=None)
        seat_score = min((room.size or 0) / 200, 1)
        coverage_score = len(matched_slots) / max(len(target_slots), 1)
        continuous_score = (longest.length if longest else 0) / 14
        score = round(coverage_score * 70 + continuous_score * 25 + seat_score * 5, 2)

        recommendations.append(
            RoomRecommendation(
                classroom=room,
                matched_slots=matched_slots,
                ranges=ranges,
                longest_range=longest,
                fits_selected_slots=fits_selected,
                score=score,
            )
        )

    recommendations.sort(
        key=lambda item: (
            item.longest_range.length if item.longest_range else 0,
            len(item.matched_slots),
            item.classroom.size or 0,
            item.score,
        ),
        reverse=True,
    )

    return RecommendationResponse(
        schedule=state,
        classrooms=classrooms,
        selected_slots=target_slots,
        recommendations=recommendations,
    )
