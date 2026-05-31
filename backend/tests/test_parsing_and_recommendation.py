from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.app.models import ClassroomStatus, ClassroomsResponse, Course
from backend.app.services.classrooms import parse_classroom, parse_idle_classroom_groups
from backend.app.services.recommender import compact_ranges, date_state, recommend
from backend.app.services.schedule import (
    encode_login,
    expand_week_numbers,
    infer_term_start_date,
    parse_cell_courses,
    parse_sjd_courses,
)


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


def test_parse_sjd_courses_from_curriculum_payload():
    payload = {
        "data": [
            {
                "item": [
                    [
                        [
                            {
                                "classWeek": "1-16",
                                "classWeekDetails": ",1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,",
                                "classTime": "1030405",
                                "weekDay": "1",
                                "courseName": "数据挖掘",
                                "teacherName": "徐思雅",
                                "buildingName": "教三楼",
                                "classroomName": "3-335",
                                "startTime": "09:50",
                                "endTIme": "12:15",
                                "jx0408id": "course-1",
                            }
                        ]
                    ]
                ]
            }
        ]
    }
    result = parse_sjd_courses(payload, "2025-2026-2", date(2026, 3, 2))
    course = result.courses[0]

    assert course.name == "数据挖掘"
    assert course.room == "教三楼-3-335"
    assert course.weekday == 1
    assert course.start_slot == 2
    assert course.end_slot == 4
    assert course.week_numbers == list(range(1, 17))


def test_infer_term_start_date_from_sjd_current_week():
    payload = {
        "data": [
            {
                "week": "14",
                "date": [
                    {"mxrq": "2026-06-01", "xqid": "1", "zc": "14"},
                    {"mxrq": "2026-06-02", "xqid": "2", "zc": "14"},
                ],
            }
        ]
    }
    assert infer_term_start_date(payload) == date(2026, 3, 2)


def test_parse_classroom_with_size():
    assert parse_classroom("教一楼-101(80)") == ("教一楼", "101", 80)


def test_parse_idle_classroom_groups_merges_slots():
    room_map = {}
    groups = [
        {
            "teachingBuildingName": "校本部-教三楼",
            "classroomList": [
                {
                    "classroomId": "335",
                    "classroomname": "335",
                    "classroomnumber": "335",
                    "seatnumber": "90",
                }
            ],
        }
    ]
    parse_idle_classroom_groups(groups, 0, room_map)
    parse_idle_classroom_groups(groups, 2, room_map)

    room = room_map["校本部-教三楼-335"]
    assert room["size"] == 90
    assert room["available_slots"] == {0, 2}


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
        provider="sjd",
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


def test_recommend_can_ignore_personal_schedule_filter():
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
        provider="sjd",
        rooms=[
            ClassroomStatus(
                id="A-101",
                building="A",
                room="101",
                name="A-101",
                size=80,
                available_slots=[2, 3],
            ),
        ],
    )
    result = recommend(
        courses,
        date(2026, 3, 2),
        classrooms,
        date(2026, 3, 2),
        [2, 3],
        [],
        0,
        use_schedule_filter=False,
    )
    assert result.selected_slots == [2, 3]
    assert result.recommendations[0].classroom.name == "A-101"


def test_recommend_respects_explicit_empty_selected_slots():
    classrooms = ClassroomsResponse(
        campus_id="01",
        campus_name="西土城",
        target_date=date(2026, 3, 2),
        fetched_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        provider="sjd",
        rooms=[
            ClassroomStatus(
                id="A-101",
                building="A",
                room="101",
                name="A-101",
                size=80,
                available_slots=[0, 1],
            ),
        ],
    )
    result = recommend([], date(2026, 3, 2), classrooms, date(2026, 3, 2), [], [], 0)
    assert result.selected_slots == []
    assert result.recommendations == []
