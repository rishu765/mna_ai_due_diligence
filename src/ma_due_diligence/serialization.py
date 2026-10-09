"""Schema-versioned deterministic JSON serialization for Project 5 domain models."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast

from ma_due_diligence import domain
from ma_due_diligence.errors import SerializationError, UnsupportedSchemaVersionError

SCHEMA_VERSION = 1
T = TypeVar("T")

_CLASS_REGISTRY: dict[str, type[Any]] = {
    name: value
    for name, value in vars(domain).items()
    if isinstance(value, type) and (is_dataclass(value) or issubclass(value, Enum))
}


def model_to_dict(model: object) -> dict[str, object]:
    """Return JSON-compatible primitives while retaining exact domain types."""

    if not is_dataclass(model) or isinstance(model, type):
        raise SerializationError("model must be a domain dataclass instance")
    return {"schema_version": SCHEMA_VERSION, "model": _encode(model)}


def model_from_dict(data: dict[str, object], expected_type: type[T]) -> T:
    """Reconstruct and type-check a model from the supported schema."""

    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"schema_version must be {SCHEMA_VERSION}, got {version!r}"
        )
    try:
        decoded = _decode(data["model"])
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, SerializationError):
            raise
        raise SerializationError(f"invalid model payload: {error}") from error
    if not isinstance(decoded, expected_type):
        raise SerializationError(
            f"payload decoded to {type(decoded).__name__}, expected {expected_type.__name__}"
        )
    return decoded


def model_to_json(model: object, *, indent: int | None = 2) -> str:
    return json.dumps(
        model_to_dict(model),
        indent=indent,
        sort_keys=True,
        ensure_ascii=False,
    )


def model_from_json(payload: str, expected_type: type[T]) -> T:
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError(f"invalid JSON: {error.msg}") from error
    if not isinstance(decoded, dict):
        raise SerializationError("JSON root must be an object")
    return model_from_dict(cast(dict[str, object], decoded), expected_type)


def _encode(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__type__": type(value).__name__,
            **{field.name: _encode(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, Enum):
        return {"__enum__": type(value).__name__, "value": value.value}
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, tuple):
        return {"__tuple__": [_encode(item) for item in value]}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise SerializationError(f"unsupported value type: {type(value).__name__}")


def _decode(value: object) -> object:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    mapping = cast(dict[str, object], value)
    if "__decimal__" in mapping:
        return Decimal(_require_string(mapping["__decimal__"], "__decimal__"))
    if "__datetime__" in mapping:
        return datetime.fromisoformat(_require_string(mapping["__datetime__"], "__datetime__"))
    if "__date__" in mapping:
        return date.fromisoformat(_require_string(mapping["__date__"], "__date__"))
    if "__tuple__" in mapping:
        items = mapping["__tuple__"]
        if not isinstance(items, list):
            raise SerializationError("__tuple__ must contain a list")
        return tuple(_decode(item) for item in items)
    if "__enum__" in mapping:
        name = _require_string(mapping["__enum__"], "__enum__")
        enum_type = _CLASS_REGISTRY.get(name)
        if enum_type is None or not issubclass(enum_type, Enum):
            raise SerializationError(f"unknown enum type: {name}")
        return enum_type(_require_string(mapping.get("value"), "enum value"))
    if "__type__" in mapping:
        name = _require_string(mapping["__type__"], "__type__")
        model_type = _CLASS_REGISTRY.get(name)
        if model_type is None or not is_dataclass(model_type):
            raise SerializationError(f"unknown model type: {name}")
        kwargs = {key: _decode(item) for key, item in mapping.items() if key != "__type__"}
        return model_type(**kwargs)
    return {key: _decode(item) for key, item in mapping.items()}


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise SerializationError(f"{name} must be a string")
    return value
