"""Shared setting-schema primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SettingKind = Literal["boolean", "integer", "number", "text", "choice", "path"]
SettingValue = int | float | bool | str | None


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    group: str
    kind: SettingKind
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    multiple_of: int | None = None
    choices: tuple[tuple[str, str], ...] = ()
    nullable: bool = False
    restart_required: bool = False

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "kind": self.kind,
            "description": self.description,
            "restart_required": self.restart_required,
        }
        if self.minimum is not None:
            payload["min"] = self.minimum
        if self.maximum is not None:
            payload["max"] = self.maximum
        if self.step is not None:
            payload["step"] = self.step
        if self.multiple_of is not None:
            payload["multiple_of"] = self.multiple_of
        if self.choices:
            payload["choices"] = [{"value": value, "label": label} for value, label in self.choices]
        if self.nullable:
            payload["nullable"] = True
        return payload


def choices(values: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((value, value) for value in values)


def boolean(
    key: str,
    label: str,
    group: str,
    description: str = "",
    *,
    restart_required: bool = False,
) -> SettingSpec:
    return SettingSpec(
        key,
        label,
        group,
        "boolean",
        description,
        restart_required=restart_required,
    )


def integer(
    key: str,
    label: str,
    group: str,
    *,
    minimum: int,
    maximum: int,
    step: int,
    multiple_of: int | None = None,
    description: str = "",
    restart_required: bool = False,
) -> SettingSpec:
    return SettingSpec(
        key,
        label,
        group,
        "integer",
        description,
        minimum=minimum,
        maximum=maximum,
        step=step,
        multiple_of=multiple_of,
        restart_required=restart_required,
    )


def number(
    key: str,
    label: str,
    group: str,
    *,
    minimum: float,
    maximum: float,
    step: float,
) -> SettingSpec:
    return SettingSpec(
        key,
        label,
        group,
        "number",
        minimum=minimum,
        maximum=maximum,
        step=step,
    )


def choice(
    key: str,
    label: str,
    group: str,
    options: tuple[tuple[str, str], ...],
) -> SettingSpec:
    return SettingSpec(key, label, group, "choice", choices=options)


def text(
    key: str,
    label: str,
    group: str,
    description: str = "",
    *,
    nullable: bool = False,
    restart_required: bool = False,
) -> SettingSpec:
    return SettingSpec(
        key,
        label,
        group,
        "text",
        description,
        nullable=nullable,
        restart_required=restart_required,
    )


def path(
    key: str,
    label: str,
    group: str,
    *,
    restart_required: bool = False,
) -> SettingSpec:
    return SettingSpec(
        key,
        label,
        group,
        "path",
        restart_required=restart_required,
    )


__all__ = [
    "SettingKind",
    "SettingSpec",
    "SettingValue",
    "boolean",
    "choice",
    "choices",
    "integer",
    "number",
    "path",
    "text",
]
