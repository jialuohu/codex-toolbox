"""Validate synthetic broker payloads against the generated 0.159.0 schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

CONTRACT = json.loads((Path(__file__).parent / "fixtures/app-server-0.159.0.json").read_text())


def schema_validator(name: str) -> Draft7Validator:
    return Draft7Validator({
        "$schema": CONTRACT["$schema"],
        "$ref": f"#/definitions/{name}",
        "definitions": CONTRACT["definitions"],
    })


def validate_client_request(method: str, params: dict[str, Any]) -> None:
    schema_validator(CONTRACT["x-client-requests"][method]).validate(params)


def validate_server_response(method: str, result: dict[str, Any]) -> None:
    schema_validator(CONTRACT["x-server-responses"][method]).validate(result)
