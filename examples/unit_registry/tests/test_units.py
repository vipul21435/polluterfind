import units


def test_known_units_are_the_defaults():
    assert units.known_units() == ["cm", "km", "m", "mile"]


def test_reset_restores_defaults():
    units.reset()
    assert "m" in units.known_units()


def test_metre_is_base():
    assert units.convert(1, "m", "m") == 1
