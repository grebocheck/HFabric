"""Persistence and event publication for completed or failed jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..backends.registry import ModelRegistry
from ..config import settings
from ..db.models import Image, Job, Video
from ..db.session import session_scope
from ..util import imaging
from .enums import EventType, JobStatus, JobType
from .events import Event, EventBus
from .llm_tools import ToolCallPlanner, strip_reasoning


@dataclass
class JobSnapshot:
    id: str
    type: JobType
    model_id: str
    params: dict[str, Any]
    queue_age_s: float = 0.0


def friendly_job_error(exc: BaseException) -> str:
    """Map a backend exception to a concise user-facing job error."""
    detail = str(exc).strip()
    lower = detail.lower()
    if "out of memory" in lower or "cuda oom" in lower:
        return "The job ran out of accelerator memory. Try a smaller size, fewer images, or a lighter model."
    if isinstance(exc, FileNotFoundError):
        return f"Required file was not found: {detail}" if detail else "Required file was not found."
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return f"Missing runtime dependency: {detail}" if detail else "Missing runtime dependency."
    if isinstance(exc, ValueError):
        return detail or "Invalid job parameters."
    name = type(exc).__name__
    return f"{name}: {detail}" if detail else f"{name}: job failed."


def split_llm_result(
    result: str | dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """Normalize plain and OpenAI-shaped backend results."""
    if not isinstance(result, dict):
        return result, []
    text = result.get("text", "")
    if isinstance(text, dict):
        return split_llm_result(text)
    raw_calls = result.get("tool_calls")
    tool_calls = raw_calls if isinstance(raw_calls, list) else []
    return str(text or ""), [call for call in tool_calls if isinstance(call, dict)]


class JobResultService:
    """Own persistence and follow-up publication after backend execution."""

    def __init__(
        self,
        bus: EventBus,
        registry: ModelRegistry,
        notify_queue: Callable[[], None],
    ) -> None:
        self._bus = bus
        self._registry = registry
        self._notify_queue = notify_queue
        self._tool_calls = ToolCallPlanner()

    def enrich_image_params(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_loras = params.get("loras") or []
        if not isinstance(raw_loras, list) or not raw_loras:
            return params
        lora_paths: dict[str, str] = {}
        for item in raw_loras:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            lora = self._registry.get_lora(item["id"])
            lora_paths[lora.id] = str(lora.path)
        if not lora_paths:
            return params
        return {**params, "_lora_paths": lora_paths}

    async def discard_images(self, records: list[dict[str, Any]]) -> None:
        """Remove generated files that will not receive durable gallery rows."""
        await asyncio.to_thread(imaging.remove_image_records, records, settings.outputs_dir)

    async def finish_image(
        self,
        snap: JobSnapshot,
        records: list[dict[str, Any]],
    ) -> None:
        image_ids: list[str] = []
        chat_markdown: str | None = None
        async with session_scope() as session:
            for record in records:
                image = Image(
                    job_id=snap.id,
                    path=record["path"],
                    thumb_path=record.get("thumb_path"),
                    seed=record.get("seed"),
                    width=record.get("width"),
                    height=record.get("height"),
                    family=record.get("family"),
                    params=record.get("params", {}),
                )
                session.add(image)
                await session.flush()
                image_ids.append(image.id)
            job = await session.get(Job, snap.id)
            if job:
                job.status = JobStatus.DONE
                job.progress = 1.0
                job.result = {"image_ids": image_ids}
                job.finished_at = datetime.now(UTC)
            if snap.params.get("assistant_message_id"):
                prompt = str(snap.params.get("prompt", "")).strip()
                chat_markdown = (
                    "\n\n".join(f"![{prompt}](/api/images/{image_id}/file)" for image_id in image_ids)
                    or "(no image produced)"
                )
                await self._write_chat_reply(session, snap, chat_markdown)

        for image_id, record in zip(image_ids, records):
            await self._bus.publish(
                Event(
                    EventType.IMAGE_READY,
                    job_id=snap.id,
                    image_id=image_id,
                    thumb=record.get("thumb_path"),
                    path=record["path"],
                    request_id=snap.params.get("_request_id"),
                )
            )
        done = Event(
            EventType.JOB_DONE,
            job_id=snap.id,
            job_type=snap.type.value,
            request_id=snap.params.get("_request_id"),
        )
        if chat_markdown is not None:
            done = Event(
                EventType.JOB_DONE,
                job_id=snap.id,
                job_type=snap.type.value,
                text=chat_markdown,
                request_id=snap.params.get("_request_id"),
            )
        await self._bus.publish(done)

    async def finish_video(
        self,
        snap: JobSnapshot,
        record: dict[str, Any],
    ) -> None:
        async with session_scope() as session:
            video = Video(
                job_id=snap.id,
                path=record["path"],
                poster_path=record.get("poster_path"),
                thumb_path=record.get("thumb_path"),
                seed=record.get("seed"),
                width=record.get("width"),
                height=record.get("height"),
                frames=record.get("frames"),
                fps=record.get("fps"),
                duration_s=record.get("duration_s"),
                family=record.get("family"),
                params=record.get("params", {}),
            )
            session.add(video)
            await session.flush()
            video_id = video.id
            job = await session.get(Job, snap.id)
            if job:
                job.status = JobStatus.DONE
                job.progress = 1.0
                job.result = {"video_id": video_id}
                job.finished_at = datetime.now(UTC)
        await self._bus.publish(
            Event(
                EventType.VIDEO_READY,
                job_id=snap.id,
                video_id=video_id,
                path=record["path"],
                poster=record.get("poster_path"),
                request_id=snap.params.get("_request_id"),
            )
        )
        await self._bus.publish(
            Event(
                EventType.JOB_DONE,
                job_id=snap.id,
                job_type=snap.type.value,
                request_id=snap.params.get("_request_id"),
            )
        )

    async def finish_llm(
        self,
        snap: JobSnapshot,
        text: str,
        native_tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        clean = strip_reasoning(text)
        reply_text = text if snap.params.get("assistant_message_id") else clean
        tool_call = await self._tool_calls.build_native_tool_call(
            native_tool_calls or [],
            clean,
            snap,
        )
        if tool_call is None:
            tool_call = self._tool_calls.parse_image_tool_call(clean, snap)
        if tool_call is None:
            tool_call = await self._tool_calls.build_document_tool_call(
                clean,
                snap,
            )

        child_job_id: str | None = None
        child_job_type: JobType | None = None
        child_text: str | None = None
        async with session_scope() as session:
            job = await session.get(Job, snap.id)
            if job:
                job.status = JobStatus.DONE
                job.progress = 1.0
                job.finished_at = datetime.now(UTC)
            if tool_call:
                child_params = dict(tool_call["params"])
                if request_id := snap.params.get("_request_id"):
                    child_params["_request_id"] = request_id
                child_job = Job(
                    type=tool_call["job_type"],
                    model_id=tool_call["model_id"],
                    params=child_params,
                    priority=0,
                    status=JobStatus.QUEUED,
                )
                session.add(child_job)
                await session.flush()
                child_job_id = child_job.id
                child_job_type = JobType(tool_call["job_type"])
                child_text = tool_call["pending_text"]
                if job:
                    job.result = {
                        "text": text,
                        "tool_call": tool_call["public"],
                        "child_job_id": child_job_id,
                    }
                await self._write_chat_reply(session, snap, child_text)
            else:
                if job:
                    job.result = {"text": reply_text}
                await self._write_chat_reply(session, snap, reply_text)

        if child_job_id:
            await self._bus.publish(
                Event(
                    EventType.JOB_CREATED,
                    job_id=child_job_id,
                    job_type=(child_job_type or JobType.LLM).value,
                    request_id=snap.params.get("_request_id"),
                )
            )
            await self._bus.publish(
                Event(
                    EventType.JOB_DONE,
                    job_id=snap.id,
                    job_type=snap.type.value,
                    text=child_text,
                    tool_child_job_id=child_job_id,
                    request_id=snap.params.get("_request_id"),
                )
            )
            self._notify_queue()
            return
        await self._bus.publish(
            Event(
                EventType.JOB_DONE,
                job_id=snap.id,
                job_type=snap.type.value,
                text=reply_text,
                request_id=snap.params.get("_request_id"),
            )
        )

    async def mark_cancelled(
        self,
        snap: JobSnapshot,
        text: str | None = None,
    ) -> None:
        async with session_scope() as session:
            job = await session.get(Job, snap.id)
            if job:
                job.status = JobStatus.CANCELLED
                job.finished_at = datetime.now(UTC)
                if text:
                    job.result = {"text": text}
            if snap.params.get("assistant_message_id"):
                note = (text + "\n\n" if text else "") + "_(cancelled)_"
                await self._write_chat_reply(session, snap, note)
        await self._bus.publish(
            Event(
                EventType.JOB_CANCELLED,
                job_id=snap.id,
                request_id=snap.params.get("_request_id"),
            )
        )

    async def fail(self, snap: JobSnapshot, error: str) -> None:
        async with session_scope() as session:
            job = await session.get(Job, snap.id)
            if job:
                job.status = JobStatus.ERROR
                job.error = error
                job.finished_at = datetime.now(UTC)
            if snap.params.get("assistant_message_id"):
                await self._write_chat_reply(
                    session,
                    snap,
                    error,
                    error=True,
                )
        await self._bus.publish(
            Event(
                EventType.JOB_ERROR,
                job_id=snap.id,
                error=error,
                request_id=snap.params.get("_request_id"),
            )
        )

    @staticmethod
    async def _write_chat_reply(
        session: Any,
        snap: JobSnapshot,
        text: str,
        *,
        error: bool = False,
    ) -> None:
        message_id = snap.params.get("assistant_message_id")
        if not message_id:
            return
        from ..services import chat_service  # noqa: PLC0415

        await chat_service.finalize_assistant_message(
            session,
            message_id,
            text,
            error=error,
        )


__all__ = [
    "JobResultService",
    "JobSnapshot",
    "friendly_job_error",
    "split_llm_result",
]
