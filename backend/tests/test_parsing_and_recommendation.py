from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.app.models import ClassroomStatus, ClassroomsResponse, Course
from backend.app.services.classrooms import parse_classroom
from backend.app.services.recommender import compact_ranges, date_state, recommend
from backend.app.services.schedule import encode_login, expand_week_numbers, parse_cell_courses


def test_encode_login_matches_reference_shape():
    assert encode_login("2023000000", "abc") == "MjAyMzAwMDAwMA==%%%YWJj"


def test_expand_week_numbers_with_odd_even():
    assert expand_week_numbers("1-5[周]") == [1, 2, 3, 4, 5]
    assert expand_week_numbers("1-5[周](单)") == [1, 3, 5]
    assert expand_week_numbers("2,4,6[周]") == [2, 4, 6]


def test_parse_cell_courses_from_bupt_cell_text():
    cell = "高等数学\n张三\n1-16[周]\n教一楼-101\n1-2节"
    parsed = parse_cell_courses(cell)
    assert parsed == [
        {
            "name": "高等数学",
            "teacher": "张三",
            "week": "1-16[周]",
            "room": "教一楼-101",
            "section": "1-2节",
        }
    ]


def test_parse_classroom_with_size():
    assert parse_classroom("教一楼-101(80)") == ("教一楼", "101", 80)


def test_compact_ranges():
    ranges = compact_ranges([0, 1, 2, 5, 6])
    assert [(item.start_slot, item.end_slot, item.length) for item in ranges] == [(0, 2, 3), (5, 6, 2)]


def test_recommend_prioritizes_longest_stay():
    courses = [
        Course(
            id="c1",
            name="课程",
            weekday=1,
            week_numbers=[1],
            start_slot=2,
            end_slot=3,
        )
    ]
    classrooms = ClassroomsResponse(
        campus_id="01",
        campus_name="西土城",
        target_date=date(2026, 3, 2),
        fetched_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        provider="jwglweixin",
        rooms=[
            ClassroomStatus(
                id="A-101",
                building="A",
                room="101",
                name="A-101",
                size=80,
                available_slots=[0, 1, 4, 5, 6, 7],
            ),
            ClassroomStatus(
                id="B-201",
                building="B",
                room="201",
                name="B-201",
                size=120,
                available_slots=[0, 4, 5],
            ),
        ],
    )
    result = recommend(courses, date(2026, 3, 2), classrooms, date(2026, 3, 2), None, [], 0)
    assert date_state(courses, date(2026, 3, 2), date(2026, 3, 2)).busy_slots == [2, 3]
    assert result.recommendations[0].classroom.name == "A-101"
    assert result.recommendations[0].longest_range.length == 4
