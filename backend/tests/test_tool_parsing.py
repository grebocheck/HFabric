"""LLM tool-call parsing — the chat->image / document bridges (pure, no DB/GPU).

A model can emit a `generate_image` JSON blob mid-reply (often wrapped in a code
fence or trailing prose); the worker must extract it robustly and clamp the
params before queuing a child image job. These lock that parsing down.
"""

from __future__ import annotations

from app.core.enums import JobType
from app.core.scheduler import JobSnapshot, Worker, _coerce_int
from app.services import prompt_service


def _worker() -> Worker:
    # _parse_image_tool_call / _extract_json_object only use static helpers on
    # self, never the bus/arbiter/registry, so dummies are fine here.
    return Worker(None, None, None)  # type: ignore[arg-type]


def _snap(params: dict) -> JobSnapshot:
    return JobSnapshot(id="j1", type=JobType.LLM, model_id="llm", params=params)


# --------------------------------------------------------------- _coerce_int


def test_coerce_int_clamps_and_defaults():
    assert _coerce_int("5", 0, min_value=1, max_value=10) == 5
    assert _coerce_int(999, 0, min_value=1, max_value=10) == 10   # upper clamp
    assert _coerce_int(-4, 0, min_value=1, max_value=10) == 1     # lower clamp
    assert _coerce_int(None, 7, min_value=1, max_value=10) == 7   # default
    assert _coerce_int("abc", 7, min_value=1, max_value=10) == 7  # unparseable


# --------------------------------------------------------- _extract_json_object


def test_extract_json_from_code_fence():
    text = 'sure!\n```json\n{"tool": "generate_image", "prompt": "x"}\n```\ndone'
    obj = Worker._extract_json_object(text)
    assert obj == {"tool": "generate_image", "prompt": "x"}


def test_extract_json_embedded_in_prose():
    text = 'Here you go: {"a": 1, "b": [2, 3]} cheers'
    assert Worker._extract_json_object(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_returns_none_when_absent():
    assert Worker._extract_json_object("no json here") is None


# ----------------------------------------------------- _parse_image_tool_call


def test_parse_image_tool_call_clamps_params():
    snap = _snap({"image_tool": {"model_id": "sdxl", "conversation_id": "c1",
                                 "assistant_message_id": "m1"}})
    text = '{"tool": "generate_image", "prompt": "a red fox", "steps": 500, "width": 99999}'
    call = _worker()._parse_image_tool_call(text, snap)
    assert call is not None
    assert call["job_type"] is JobType.IMAGE
    assert call["model_id"] == "sdxl"
    p = call["params"]
    assert p["prompt"] == "a red fox"
    assert p["steps"] == 80      # clamped to max
    assert p["width"] == 2048    # clamped to max
    assert p["height"] == 768    # default
    assert p["source_llm_job_id"] == "j1"
    assert call["public"]["tool"] == "generate_image"


def test_parse_image_tool_call_accepts_arguments_wrapper():
    snap = _snap({"image_tool": {"model_id": "sdxl"}})
    text = '{"name": "generate_image", "arguments": {"prompt": "castle", "negative": "blurry"}}'
    call = _worker()._parse_image_tool_call(text, snap)
    assert call is not None
    assert call["params"]["prompt"] == "castle"
    assert call["params"]["negative"] == "blurry"


def test_native_tool_call_arguments_parse_from_openai_shape():
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "generate_image", "arguments": '{"prompt":"castle"}'},
    }
    name, args = Worker._native_tool_name_args(call)
    assert name == "generate_image"
    assert args == {"prompt": "castle"}


async def test_native_image_tool_call_uses_same_builder():
    snap = _snap({"image_tool": {"model_id": "sdxl", "conversation_id": "c1",
                                 "assistant_message_id": "m1"}})
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "generate_image", "arguments": '{"prompt":"native castle"}'},
    }
    built = await _worker()._build_native_tool_call([call], "", snap)
    assert built is not None
    assert built["model_id"] == "sdxl"
    assert built["params"]["prompt"] == "native castle"


def test_parse_image_tool_call_requires_config():
    snap = _snap({})  # no image_tool config
    text = '{"tool": "generate_image", "prompt": "x"}'
    assert _worker()._parse_image_tool_call(text, snap) is None


def test_parse_image_tool_call_rejects_other_tools_and_empty_prompt():
    snap = _snap({"image_tool": {"model_id": "sdxl"}})
    assert _worker()._parse_image_tool_call('{"tool": "something_else"}', snap) is None
    assert _worker()._parse_image_tool_call('{"tool": "generate_image", "prompt": "  "}', snap) is None


# --------------------------------------------------------------- prompt_service


def test_expansion_params_carry_system_and_idea():
    params = prompt_service.build_expansion_params("a lighthouse")
    assert params["system"] == prompt_service.SYSTEM_TEMPLATE
    assert params["prompt"] == "a lighthouse"
    assert params["max_tokens"] == 300


def test_expansion_params_append_style():
    params = prompt_service.build_expansion_params("  a lighthouse  ", style="watercolor")
    assert params["prompt"] == "a lighthouse\n\nPreferred style: watercolor"
