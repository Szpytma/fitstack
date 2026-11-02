"""`normalize_weather` — one unit per reading, not one per field.

Garmin reports temperature in the account's unit and names the unit nowhere in
the payload, so it has to be inferred. The bug this pins shipped for months: the
inference ran per field, so a single reading came back split across both scales.
"""

from __future__ import annotations

from app.providers.garmin import normalize_weather


def temps(weather: dict) -> tuple[float | None, float | None]:
    """`(temp_c, apparent_c)` — the two fields most of these tests care about."""
    out = normalize_weather(weather)
    return out["temp_c"], out["apparent_c"]


def test_a_cold_fahrenheit_reading_converts_every_field():
    """The failure as found: 46F/43F/43F on a 7C London morning.

    Deciding per field converted `temp` (46 > 45) and left `apparentTemp`
    alone (43 < 45), so the activity page reported 7.8 C feeling like 43 C.
    """
    temp_c, apparent_c = temps(
        {"temp": 46, "apparentTemp": 43, "dewPoint": 43}
    )
    assert temp_c is not None and apparent_c is not None
    assert round(temp_c, 1) == 7.8
    assert round(apparent_c, 1) == 6.1
    # The headline figure must never be the colder of the two here: a wind on a
    # damp morning makes it feel cooler, not 35 degrees warmer.
    assert apparent_c < temp_c


def test_celsius_is_left_alone():
    assert temps(
        {"temp": 18, "apparentTemp": 17, "dewPoint": 12}
    ) == (18.0, 17.0)


def test_dew_point_never_votes():
    """It cannot be evidence, and it can do harm.

    Dew point is never above air temperature, so a Fahrenheit dew point over
    the threshold implies `temp` is over it too — `temp` has already decided.
    What a stray value *can* do is flip a correct reading: this payload is a
    mild Celsius day with a sentinel where the dew point should be, and both
    reported figures must come through untouched.
    """
    assert temps(
        {"temp": 18, "apparentTemp": 17, "dewPoint": 999}
    ) == (18.0, 17.0)


def test_a_hot_humid_celsius_day_is_not_mistaken_for_fahrenheit():
    """Apparent temperature is a heat index and legitimately clears 45 C.

    38 C air feeling like 50 C is a real summer reading. Letting the
    feels-like figure vote on the unit would convert the whole thing and
    report a 38 C day as 3 C — a worse failure than the one this guards,
    because it looks plausible.
    """
    assert temps({"temp": 38, "apparentTemp": 50}) == (38.0, 50.0)


def test_hot_fahrenheit_converts():
    temp_c, apparent_c = temps(
        {"temp": 90, "apparentTemp": 95, "dewPoint": 70}
    )
    assert temp_c is not None and apparent_c is not None
    assert round(temp_c, 1) == 32.2
    assert round(apparent_c, 1) == 35.0


def test_missing_fields_stay_missing():
    assert temps({}) == (None, None)
    assert temps({"temp": None, "apparentTemp": None}) == (None, None)


def test_apparent_alone_is_enough_to_convert():
    """`temp` can be absent; the reading is still one unit."""
    temp_c, apparent_c = temps({"apparentTemp": 86})
    assert temp_c is None
    assert apparent_c is not None and round(apparent_c, 1) == 30.0


def test_wind_follows_the_temperature_into_metric():
    """Wind cannot vote on the unit, so it has to ride on the decision.

    Garmin reports mph on a Fahrenheit account and km/h on a Celsius one, and
    the field was mapped straight through — so an imperial reading was mph
    under a `wind_kph` label, 38% low. 6 mph is 9.7 km/h.
    """
    assert normalize_weather(
        {"temp": 46, "apparentTemp": 43, "windSpeed": 6}
    )["wind_kph"] == 9.7


def test_metric_wind_is_left_alone():
    assert normalize_weather({"temp": 18, "windSpeed": 6})["wind_kph"] == 6


def test_wind_has_no_vote_of_its_own():
    """There is no threshold to test: 20 is ordinary in either unit.

    A metric reading with a brisk wind must not be mistaken for imperial just
    because the number is large.
    """
    out = normalize_weather({"temp": 12, "apparentTemp": 10, "windSpeed": 48})
    assert out["temp_c"] == 12.0
    assert out["wind_kph"] == 48


def test_missing_wind_stays_missing():
    assert normalize_weather({"temp": 46, "windSpeed": None})["wind_kph"] is None
    assert normalize_weather({"temp": 46})["wind_kph"] is None


def test_humidity_and_conditions_come_through():
    out = normalize_weather(
        {"temp": 46, "relativeHumidity": 87, "weatherTypeDTO": {"desc": "Mostly Cloudy"}}
    )
    assert out["humidity"] == 87
    assert out["conditions"] == "Mostly Cloudy"
