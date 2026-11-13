import pytest
import units


def test_km_to_m():
    assert units.convert(2, "km", "m") == 2000


def test_cm_to_m():
    assert units.convert(250, "cm", "m") == pytest.approx(2.5)


def test_mile_to_km():
    assert units.convert(1, "mile", "km") == pytest.approx(1.609344)


def test_identity():
    assert units.convert(7, "m", "m") == 7


def test_unknown_unit():
    with pytest.raises(KeyError):
        units.convert(1, "parsec", "m")
