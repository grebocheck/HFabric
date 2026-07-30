"""Characterization tests for the composed writable-settings schema."""

from collections import Counter

from app.services.settings_spec_sections.image import IMAGE_SPECS
from app.services.settings_spec_sections.performance import PERFORMANCE_SPECS
from app.services.settings_spec_sections.runtime import RUNTIME_SPECS
from app.services.settings_spec_sections.sources import SOURCE_SPECS
from app.services.settings_spec_sections.tools import TOOL_SPECS
from app.services.settings_specs import GROUPS, SPECS


def test_settings_sections_compose_in_ui_order():
    assert SPECS == (
        *RUNTIME_SPECS,
        *IMAGE_SPECS,
        *PERFORMANCE_SPECS,
        *TOOL_SPECS,
        *SOURCE_SPECS,
    )
    assert [group["id"] for group in GROUPS] == [
        "runtime",
        "paths",
        "llm",
        "image_defaults",
        "family_defaults",
        "acceleration",
        "memory",
        "tools",
        "voice",
        "sources",
    ]


def test_settings_inventory_is_unique_and_group_complete():
    keys = [spec.key for spec in SPECS]
    group_ids = {group["id"] for group in GROUPS}

    assert len(keys) == len(set(keys)) == 140
    assert {spec.group for spec in SPECS} == group_ids
    assert Counter(spec.group for spec in SPECS) == {
        "runtime": 1,
        "paths": 12,
        "llm": 7,
        "image_defaults": 20,
        "family_defaults": 32,
        "acceleration": 20,
        "memory": 7,
        "tools": 11,
        "voice": 12,
        "sources": 18,
    }


def test_setting_payload_keeps_optional_contract_fields():
    by_key = {spec.key: spec for spec in SPECS}

    width = by_key["default_width"].payload()
    assert width["min"] == 256
    assert width["max"] == 2048
    assert width["step"] == 64
    assert width["multiple_of"] == 64

    resize = by_key["image_edit_resize_mode"].payload()
    assert resize["choices"] == [
        {"value": "crop", "label": "crop"},
        {"value": "pad", "label": "pad"},
        {"value": "stretch", "label": "stretch"},
    ]

    controlnet = by_key["sdxl_controlnet_canny_repo"].payload()
    assert controlnet["nullable"] is True
    assert controlnet["restart_required"] is True
