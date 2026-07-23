"""Canonical composition of writable runtime setting specifications."""

from .settings_spec_sections.groups import GROUPS
from .settings_spec_sections.image import IMAGE_SPECS
from .settings_spec_sections.performance import PERFORMANCE_SPECS
from .settings_spec_sections.runtime import RUNTIME_SPECS
from .settings_spec_sections.schema import (
    SettingKind,
    SettingSpec,
    SettingValue,
)
from .settings_spec_sections.sources import SOURCE_SPECS
from .settings_spec_sections.tools import TOOL_SPECS

SPECS: tuple[SettingSpec, ...] = (
    *RUNTIME_SPECS,
    *IMAGE_SPECS,
    *PERFORMANCE_SPECS,
    *TOOL_SPECS,
    *SOURCE_SPECS,
)

__all__ = [
    "GROUPS",
    "SPECS",
    "SettingKind",
    "SettingSpec",
    "SettingValue",
]
