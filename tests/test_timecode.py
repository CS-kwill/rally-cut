import pytest
from rally_cut.timecode import parse_tc, format_tc


@pytest.mark.parametrize("text,expected", [
    ("00:00:12", 12.0),
    ("00:01:05", 65.0),
    ("01:02:03", 3723.0),
    ("00:00:38.500", 38.5),
    ("90", 90.0),          # bare seconds
    ("1:30", 90.0),        # M:S
])
def test_parse_tc(text, expected):
    assert parse_tc(text) == pytest.approx(expected)


@pytest.mark.parametrize("seconds,expected", [
    (12.0, "00:00:12.000"),
    (65.0, "00:01:05.000"),
    (3723.0, "01:02:03.000"),
    (38.5, "00:00:38.500"),
])
def test_format_tc(seconds, expected):
    assert format_tc(seconds) == expected


def test_roundtrip():
    assert parse_tc(format_tc(123.456)) == pytest.approx(123.456, abs=1e-3)


def test_parse_invalid():
    with pytest.raises(ValueError):
        parse_tc("abc")
