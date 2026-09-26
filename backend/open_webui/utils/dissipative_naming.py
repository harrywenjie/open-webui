"""Explicit compatibility for renamed environment settings."""
import os


def setting(name: str, default=None):
    value = os.environ.get(name)
    if not name.startswith("DISSIPATIVE_"):
        return default if value is None else value
    legacy = os.environ.get("CHAT_MEMORY_" + name[len("DISSIPATIVE_"):])
    if value is not None and legacy is not None and value != legacy:
        raise ValueError("conflicting environment setting: " + name)
    return value if value is not None else legacy if legacy is not None else default


def normalize_environment():
    for name in tuple(os.environ):
        if name.startswith("CHAT_MEMORY_"):
            canonical = "DISSIPATIVE_" + name[len("CHAT_MEMORY_"):]
            os.environ[canonical] = setting(canonical)
