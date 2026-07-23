"""Parsing and follow-up job planning for LLM tool calls."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from ..db.session import session_scope
from ..services.rag_service import search_documents as run_rag_search
from .enums import JobType

if TYPE_CHECKING:
    from .job_results import JobSnapshot

_THINK_RE = re.compile(
    r"<think(?:ing)?>.*?</think(?:ing)?>",
    re.IGNORECASE | re.DOTALL,
)


def coerce_int(
    value: Any,
    default: int,
    *,
    min_value: int,
    max_value: int,
) -> int:
    """Convert an untrusted tool argument to a bounded integer."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, number))


def strip_reasoning(text: str) -> str:
    """Remove complete ``think`` blocks from non-chat LLM output."""
    return _THINK_RE.sub("", text).strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from fenced or prose-wrapped output."""
    cleaned = text.strip()
    fenced = re.search(
        r"```(?:json)?\s*(\{[\s\S]*?\})\s*```",
        cleaned,
        re.IGNORECASE,
    )
    if fenced:
        cleaned = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def native_tool_name_args(
    call: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """Normalize OpenAI-style and flattened native tool calls."""
    function = call.get("function")
    function_data = function if isinstance(function, dict) else {}
    name = function_data.get("name") or call.get("name")
    raw_args = function_data.get("arguments", {})
    if isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            parsed = {}
        args = parsed if isinstance(parsed, dict) else {}
    else:
        args = {}
    return str(name) if name else None, args


class ToolCallPlanner:
    """Translate LLM tool output into validated child-job descriptions."""

    async def build_native_tool_call(
        self,
        calls: list[dict[str, Any]],
        assistant_text: str,
        snap: JobSnapshot,
    ) -> dict[str, Any] | None:
        for call in calls:
            name, args = native_tool_name_args(call)
            if name == "generate_image":
                built = self._build_image_tool_call(args, snap)
                if built is not None:
                    built["native_tool_call"] = call
                    return built
            if name == "search_documents":
                built = await self._build_document_tool_call_from_args(
                    args,
                    snap,
                    assistant_text=assistant_text,
                    native_call=call,
                )
                if built is not None:
                    return built
        return None

    def parse_image_tool_call(
        self,
        text: str,
        snap: JobSnapshot,
    ) -> dict[str, Any] | None:
        config = snap.params.get("image_tool")
        if not isinstance(config, dict) or not config.get("model_id"):
            return None
        obj = extract_json_object(text)
        if not isinstance(obj, dict):
            return None
        tool = obj.get("tool") or obj.get("name")
        args = obj.get("arguments") if isinstance(obj.get("arguments"), dict) else obj
        if tool != "generate_image" or not isinstance(args, dict):
            return None
        return self._build_image_tool_call(args, snap)

    def _build_image_tool_call(
        self,
        args: dict[str, Any],
        snap: JobSnapshot,
    ) -> dict[str, Any] | None:
        config = snap.params.get("image_tool")
        if not isinstance(config, dict) or not config.get("model_id"):
            return None
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return None
        image_params: dict[str, Any] = {
            "prompt": prompt,
            "assistant_message_id": config.get("assistant_message_id"),
            "conversation_id": config.get("conversation_id"),
            "source_llm_job_id": snap.id,
        }
        negative = str(args.get("negative") or "").strip()
        if negative:
            image_params["negative"] = negative
        image_params["steps"] = coerce_int(
            args.get("steps"),
            12,
            min_value=1,
            max_value=80,
        )
        image_params["width"] = coerce_int(
            args.get("width"),
            768,
            min_value=256,
            max_value=2048,
        )
        image_params["height"] = coerce_int(
            args.get("height"),
            768,
            min_value=256,
            max_value=2048,
        )
        if args.get("seed") is not None:
            image_params["seed"] = coerce_int(
                args.get("seed"),
                -1,
                min_value=-1,
                max_value=2_147_483_647,
            )
        image_params["tool_call"] = "generate_image"
        public = {
            "tool": "generate_image",
            "prompt": prompt,
            "negative": negative,
            "steps": image_params["steps"],
            "width": image_params["width"],
            "height": image_params["height"],
        }
        return {
            "job_type": JobType.IMAGE,
            "model_id": str(config["model_id"]),
            "params": image_params,
            "public": public,
            "pending_text": f"*generating image...*\n\n`{prompt}`",
        }

    async def build_document_tool_call(
        self,
        text: str,
        snap: JobSnapshot,
    ) -> dict[str, Any] | None:
        obj = extract_json_object(text)
        if not isinstance(obj, dict):
            return None
        tool = obj.get("tool") or obj.get("name")
        args = obj.get("arguments") if isinstance(obj.get("arguments"), dict) else obj
        if tool != "search_documents" or not isinstance(args, dict):
            return None
        return await self._build_document_tool_call_from_args(
            args,
            snap,
            assistant_text=text,
        )

    async def _build_document_tool_call_from_args(
        self,
        args: dict[str, Any],
        snap: JobSnapshot,
        *,
        assistant_text: str,
        native_call: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        config = snap.params.get("document_tool")
        if not isinstance(config, dict):
            return None
        query = str(args.get("query") or "").strip()
        if not query:
            return None
        top_k = coerce_int(
            args.get("top_k"),
            int(config.get("top_k") or 5),
            min_value=1,
            max_value=20,
        )

        try:
            async with session_scope() as session:
                result = await run_rag_search(
                    session,
                    query=query,
                    top_k=top_k,
                )
        except Exception as exc:  # noqa: BLE001
            context = f"Document search failed: {exc}"
            results: list[dict[str, Any]] = []
        else:
            context = str(result.get("context") or "").strip()
            results = list(result.get("results") or [])

        if not context:
            context = "No matching local documents were found."

        messages = list(snap.params.get("messages") or [])
        tool_content = (
            f"{context}\n\n"
            "Answer the user's latest question using this retrieved context when relevant. "
            "Cite bracketed source numbers like [1] when you use a retrieved source. "
            "If the context is insufficient, say what is missing."
        )
        if native_call is not None:
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text.strip(),
                    "tool_calls": [native_call],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(native_call.get("id") or "call_0"),
                    "name": "search_documents",
                    "content": tool_content,
                }
            )
        else:
            messages.append({"role": "assistant", "content": assistant_text.strip()})
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool result from search_documents:\n\n{tool_content}",
                }
            )
        child_params = self._child_llm_params(snap, messages)
        child_params["tool_result"] = {
            "tool": "search_documents",
            "query": query,
            "top_k": top_k,
            "results": results,
        }
        public = {
            "tool": "search_documents",
            "query": query,
            "top_k": top_k,
            "matches": len(results),
        }
        return {
            "job_type": JobType.LLM,
            "model_id": snap.model_id,
            "params": child_params,
            "public": public,
            "pending_text": f"*searching documents...*\n\n`{query}`",
        }

    @staticmethod
    def _child_llm_params(
        snap: JobSnapshot,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "messages": messages,
            "assistant_message_id": snap.params.get("assistant_message_id"),
            "conversation_id": snap.params.get("conversation_id"),
            "source_llm_job_id": snap.id,
            "temperature": snap.params.get("temperature", 0.8),
            "max_tokens": snap.params.get("max_tokens", 4096),
        }
        for key in ("top_p", "top_k", "min_p", "repeat_penalty", "seed", "stop"):
            if snap.params.get(key) is not None:
                params[key] = snap.params[key]
        return params


__all__ = [
    "ToolCallPlanner",
    "coerce_int",
    "extract_json_object",
    "native_tool_name_args",
    "strip_reasoning",
]
