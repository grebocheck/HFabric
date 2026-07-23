"""Regression checks for generated-client-safe REST response contracts."""

from __future__ import annotations

from typing import Any

from app.main import app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _named_json_schema(schema: dict[str, Any]) -> bool:
    if "$ref" in schema:
        return True
    if schema.get("type") == "array":
        items = schema.get("items")
        return isinstance(items, dict) and "$ref" in items
    return False


def test_all_json_success_responses_use_named_models() -> None:
    """Never regress generated 2xx types to anonymous ``object`` schemas."""

    anonymous: list[str] = []
    document = app.openapi()
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith("2"):
                    continue
                content = response.get("content", {})
                for media_type, media in content.items():
                    if media_type != "application/json":
                        continue
                    schema = media.get("schema", {})
                    if not _named_json_schema(schema):
                        anonymous.append(
                            f"{method.upper()} {path} {status}: {schema!r}"
                        )

    assert anonymous == []


def test_non_json_success_responses_are_explicit_binary_streams() -> None:
    undocumented: list[str] = []
    document = app.openapi()
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith("2"):
                    continue
                for media_type, media in response.get("content", {}).items():
                    if media_type == "application/json":
                        continue
                    schema = media.get("schema", {})
                    if schema.get("type") != "string" or schema.get("format") != "binary":
                        undocumented.append(
                            f"{method.upper()} {path} {status} {media_type}: "
                            f"{schema!r}"
                        )

    assert undocumented == []


def test_api_operations_document_structured_errors() -> None:
    missing: list[str] = []
    document = app.openapi()
    expected = {"$ref": "#/components/schemas/ErrorOut"}
    for path, path_item in document["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            schema = (
                operation.get("responses", {})
                .get("400", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if schema != expected:
                missing.append(f"{method.upper()} {path}: {schema!r}")

    assert missing == []
