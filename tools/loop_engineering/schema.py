from __future__ import annotations

import re
from typing import Any


class SchemaError(ValueError):
    pass


def validate_instance(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise SchemaError(f"{path} must be an object")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise SchemaError(f"{path} schema properties must be an object")
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise SchemaError(f"{path} schema required must be a string list")
        missing = [item for item in required if item not in value]
        if missing:
            raise SchemaError(f"{path} is missing required fields: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise SchemaError(f"{path} has unexpected fields: {', '.join(extras)}")
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                if not isinstance(child_schema, dict):
                    raise SchemaError(f"{path}.{key} schema must be an object")
                validate_instance(child, child_schema, f"{path}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise SchemaError(f"{path} must be an array")
        _check_count(value, schema, path)
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, dict):
                raise SchemaError(f"{path} item schema must be an object")
            for index, child in enumerate(value):
                validate_instance(child, item_schema, f"{path}[{index}]")
    elif expected == "string":
        if not isinstance(value, str):
            raise SchemaError(f"{path} must be a string")
        _check_count(value, schema, path)
        pattern = schema.get("pattern")
        invalid_pattern = not isinstance(pattern, str) or re.search(pattern, value) is None
        if pattern is not None and invalid_pattern:
            raise SchemaError(f"{path} does not match its required pattern")
    elif expected is not None:
        raise SchemaError(f"{path} uses unsupported schema type {expected!r}")

    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or value not in enum):
        raise SchemaError(f"{path} is not an allowed value")


def _check_count(value: list[Any] | str, schema: dict[str, Any], path: str) -> None:
    minimum = schema.get("minItems", schema.get("minLength"))
    maximum = schema.get("maxItems", schema.get("maxLength"))
    if minimum is not None and len(value) < int(minimum):
        raise SchemaError(f"{path} is shorter than the minimum")
    if maximum is not None and len(value) > int(maximum):
        raise SchemaError(f"{path} exceeds the maximum")
