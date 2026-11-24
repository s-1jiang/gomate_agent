from types import SimpleNamespace

import pytest

from app.workflows.nearby import compact_pair, resume_recommendation


def context():
    return {
        "city": "大连市",
        "recommendation_context": {
            "anchor_name": "大连理工大学",
            "tasks": [{"agent": "activity", "keyword": "台球", "instruction": "打台球"}],
        },
        "recommendation_groups": [
            {
                "area": {
                    "provider": "amap",
                    "poi_id": "campus",
                    "name": "大连理工大学(凌水校区)",
                    "city": "大连市",
                    "city_code": "0411",
                    "address": "示例路",
                    "category": "大学",
                    "district": "",
                    "source_ref": "amap:poi:campus",
                    "fetched_at": "2026-11-24T00:00:00Z",
                    "location": {
                        "longitude": 121.5,
                        "latitude": 38.8,
                        "coordinate_system": "GCJ02",
                    },
                }
            }
        ],
    }


@pytest.mark.parametrize(
    "text", ["凌水校区", "我在凌水校区", "第一个", "凌水", "大连理工大学（凌水校区）"]
)
def test_campus_selection_resumes_with_the_same_tasks_and_observed_area(text):
    decision, area = resume_recommendation(text, context())
    assert area.poi_id == "campus" and decision.city == "大连市"
    assert decision.tasks[0].keyword == "台球"


@pytest.mark.parametrize(
    "text", ["凌水校区有什么历史？", "换个城市吧", "第二个", "200元", "吧", "怎么登录"]
)
def test_new_questions_and_unknown_choices_are_not_overridden_by_old_recommendations(text):
    assert resume_recommendation(text, context()) is None


def test_ranked_supervisor_recommendations_are_not_replaced_with_a_distance_only_choice():
    preferred = SimpleNamespace(agent="dining", name="更适合看书的选择")
    nearest = SimpleNamespace(agent="dining", name="距离更近的另一家")
    park = SimpleNamespace(agent="activity", name="公园")
    assert compact_pair([preferred, nearest, park]) == [preferred, park]
    assert compact_pair([park, preferred, nearest], first_agent="activity") == [park, preferred]
