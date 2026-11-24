from types import SimpleNamespace

import pytest

from app.planning.places import match_origin, recommendation_areas


def place(name, city="大连市"):
    return SimpleNamespace(name=name, city=city)


@pytest.mark.parametrize("name", ["星海广场沙滩", "大连星海广场沙滩", "大连市星海广场沙滩"])
def test_exact_origin_can_include_known_city_prefix(name):
    beach, square = place("星海广场沙滩"), place("星海广场")
    assert match_origin(name, [square, beach], "大连市") is beach


def test_city_prefix_does_not_hide_real_ambiguity_or_allow_partial_match():
    first, second = place("星海广场"), place("星海广场")
    assert match_origin("大连星海广场", [first, second], "大连市") is None
    assert match_origin("星海", [first, place("星海公园")], "大连市") is None
    assert match_origin("北京星海广场", [first, place("星海公园")], "大连市") is None


@pytest.mark.parametrize("name", ["凌水校区", "大连理工大学凌水校区", "大连理工大学（凌水校区）"])
def test_selected_campus_is_resolved_without_building_or_technology_centre_ambiguity(name):
    campus = place("大连理工大学(凌水校区)")
    candidates = [
        campus,
        place("大连理工大学(凌水校区技术中心)"),
        place("大连理工大学凌水校区西校区1号楼"),
    ]
    assert match_origin(name, candidates, "大连市") is campus


def test_general_university_can_offer_two_observed_campuses_instead_of_asking():
    lingshui = place("大连理工大学(凌水校区)")
    old_campus = place("大连理工大学一二九校区")
    medical = place("大连理工大学-医学部")
    assert recommendation_areas("大连理工大学", [lingshui, medical, old_campus], "大连市") == [
        lingshui,
        old_campus,
    ]
    assert recommendation_areas("凌水校区", [lingshui, old_campus], "大连市") == [lingshui]


def test_selected_campus_still_does_not_choose_between_genuinely_duplicate_campuses():
    assert (
        match_origin("凌水校区", [place("大学(凌水校区)"), place("大学(凌水校区)")], "大连市")
        is None
    )
