from types import SimpleNamespace

import pytest

from app.planning.places import match_origin


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
