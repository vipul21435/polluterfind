"""A tiny unit converter with a module-level registry (the shared state in this example)."""

_DEFAULTS = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mile": 1609.344}
_REGISTRY = dict(_DEFAULTS)


def register(name: str, metres: float) -> None:
    _REGISTRY[name] = metres


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def reset() -> None:
    _REGISTRY.clear()
    _REGISTRY.update(_DEFAULTS)


def known_units() -> list[str]:
    return sorted(_REGISTRY)


def convert(value: float, source: str, target: str) -> float:
    return value * _REGISTRY[source] / _REGISTRY[target]
