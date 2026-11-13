import pytest
import units


def test_register_and_remove_inch():
    units.register("inch", 0.0254)
    assert units.convert(100, "inch", "m") == pytest.approx(2.54)
    units.unregister("inch")


def test_register_furlong():
    # Registers a unit and never removes it: the registry stays changed for later tests.
    units.register("furlong", 201.168)
    assert units.convert(1, "furlong", "m") == pytest.approx(201.168)


def test_round_trip():
    assert units.convert(units.convert(3, "km", "mile"), "mile", "km") == pytest.approx(3)
