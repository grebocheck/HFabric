"""Chat workspace API: persistent conversations + messages.

Sending a message persists the user turn, creates an empty assistant message,
and queues an LLM job (same arbiter/queue as everything else). The reply streams
over the WebSocket as ``llm.token`` and the worker writes the final text back
into the assistant message, so conversations survive a refresh/restart.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..backends.base import ModelDescriptor
from ..backends.registry import ModelRegistry
from ..config import settings
from ..core.enums import EventType, JobType
from ..core.events import EventBus
from ..core.scheduler import Worker
from ..db.models import Conversation, Message
from ..schemas import (
    ChatAttachmentOut,
    ChatImportIn,
    ChatImportOut,
    ChatSend,
    ChatSendOut,
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    ConversationUpdate,
    ImageChatSend,
    JobCreate,
    MessageOut,
)
from ..services import chat_attachments, chat_service, queue_service
from ..util.uploads import resolve_chat_upload, store_chat_upload
from .deps import get_bus, get_registry, get_session, get_worker

router = APIRouter(prefix="/api/chat", tags=["chat"])

IMAGE_TOOL_SYSTEM = (
    "You can call one local tool when the user wants an image generated. "
    "If an image should be generated, reply with only this JSON object and no markdown: "
    '{"tool":"generate_image","prompt":"detailed image prompt","negative":"","steps":12,'
    '"width":768,"height":768}. '
    "Use the tool only when generation is useful; otherwise answer normally."
)

DOCUMENT_TOOL_SYSTEM = (
    "You can call one local tool when the user's question may need indexed local "
    "documents. If local document search would help, reply with only this JSON "
    "object and no markdown: "
    '{"tool":"search_documents","query":"concise search query","top_k":5}. '
    "Use the tool only when retrieval is useful; otherwise answer normally."
)


def _require_job_type(registry: ModelRegistry, model_id: str, job_type: JobType) -> ModelDescriptor:
    try:
        desc = registry.get_descriptor(model_id)
    except KeyError:
        raise HTTPException(404, f"unknown model_id: {model_id}")
    if desc.job_type is not job_type:
        raise HTTPException(400, f"model '{desc.id}' is not {job_type.value}")
    return desc


def _chat_tools(body: ChatSend) -> list[dict]:
    tools: list[dict] = []
    if body.image_tool:
        tools.append({
            "type": "function",
            "function": {
                "name": "generate_image",
                "description": "Queue a local image generation job when the user wants a new image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Detailed image prompt."},
                        "negative": {"type": "string", "description": "Optional negative prompt."},
                        "steps": {"type": "integer", "minimum": 1, "maximum": 80},
                        "width": {"type": "integer", "minimum": 256, "maximum": 2048},
                        "height": {"type": "integer", "minimum": 256, "maximum": 2048},
                        "seed": {"type": "integer", "minimum": -1, "maximum": 2147483647},
                    },
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
        })
    if body.document_tool:
        tools.append({
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "Search indexed local RAG documents for context relevant to the user question.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Concise semantic search query."},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        })
    return tools


def _history_content(message: Message, *, allow_images: bool) -> str | list[dict]:
    if allow_images:
        return chat_attachments.history_message_content(message)
    return message.content


def _estimate_history_tokens(
    *,
    system: str,
    history: list[Message],
    user_text: str,
    attachments: list[dict],
) -> int:
    chars = len(system) + len(user_text) + sum(len(m.content or "") for m in history)
    image_tokens = sum(
        chat_attachments.IMAGE_TOKEN_COST
        for item in attachments
        if item.get("kind") == "image"
    )
    return chars // 4 + image_tokens


def _conversation_detail(conv: Conversation, messages: list[Message]) -> ConversationDetailOut:
    base = ConversationOut.model_validate(conv)
    return ConversationDetailOut(
        **base.model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.post("/uploads", response_model=ChatAttachmentOut)
async def upload_chat_attachment(file: UploadFile = File(...)) -> ChatAttachmentOut:
    max_bytes = settings.vision_max_upload_mb * 1024 * 1024
    return ChatAttachmentOut.model_validate(await store_chat_upload(file, max_bytes=max_bytes))


@router.get("/uploads/{token}/file")
async def get_chat_upload(token: str) -> FileResponse:
    resolved = resolve_chat_upload(token)
    if resolved is None:
        raise HTTPException(404, "attachment not found")
    path, meta = resolved
    return FileResponse(
        path,
        media_type=str(meta.get("content_type") or "application/octet-stream"),
        filename=str(meta.get("filename") or path.name),
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(session: AsyncSession = Depends(get_session)) -> list[ConversationOut]:
    convs = await chat_service.list_conversations(session)
    return [ConversationOut.model_validate(c) for c in convs]


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate, session: AsyncSession = Depends(get_session)
) -> ConversationOut:
    conv = await chat_service.create_conversation(
        session, title=body.title, model_id=body.model_id, system=body.system, params=body.params
    )
    await session.commit()
    return ConversationOut.model_validate(conv)


@router.get("/conversations/{conv_id}", response_model=ConversationDetailOut)
async def get_conversation(conv_id: str, session: AsyncSession = Depends(get_session)) -> ConversationDetailOut:
    conv = await chat_service.get_conversation(session, conv_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    messages = await chat_service.get_messages(session, conv_id)
    # Build from the flat ConversationOut so pydantic never touches the lazy
    # `conv.messages` relationship (that would trigger async IO -> MissingGreenlet).
    return _conversation_detail(conv, messages)


@router.post("/import", response_model=ChatImportOut)
async def import_conversations(
    body: ChatImportIn, session: AsyncSession = Depends(get_session)
) -> ChatImportOut:
    imported: list[ConversationDetailOut] = []

    for item in body.conversations:
        title = (item.title or "").strip()
        first_user = next((m.content.strip() for m in item.messages if m.role == "user" and m.content.strip()), "")
        conv = Conversation(
            title=(title or first_user[:60] or "Imported chat")[:200],
            model_id=item.model_id,
            system=item.system,
            params=item.params,
        )
        if item.created_at:
            conv.created_at = item.created_at
        if item.updated_at or item.created_at:
            conv.updated_at = item.updated_at or item.created_at
        session.add(conv)
        await session.flush()

        messages: list[Message] = []
        for msg in item.messages:
            row = Message(
                conversation_id=conv.id,
                role=msg.role,
                content=msg.content,
                attachments=[a.model_dump() for a in msg.attachments],
                error=msg.error,
            )
            if msg.created_at:
                row.created_at = msg.created_at
            session.add(row)
            messages.append(row)

        await session.flush()
        imported.append(_conversation_detail(conv, messages))

    await session.commit()
    return ChatImportOut(imported=len(imported), conversations=imported)


@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
async def update_conversation(
    conv_id: str, body: ConversationUpdate, session: AsyncSession = Depends(get_session)
) -> ConversationOut:
    conv = await chat_service.update_conversation(
        session, conv_id, title=body.title, model_id=body.model_id,
        system=body.system, params=body.params,
    )
    if not conv:
        raise HTTPException(404, "conversation not found")
    await session.commit()
    return ConversationOut.model_validate(conv)


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    ok = await chat_service.delete_conversation(session, conv_id)
    if not ok:
        raise HTTPException(404, "conversation not found")
    await session.commit()
    return {"deleted": True}


@router.delete("/conversations/{conv_id}/messages/{message_id}")
async def truncate_messages(
    conv_id: str, message_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    """Delete a message and everything after it — used for edit & regenerate."""
    removed = await chat_service.truncate_from(session, conv_id, message_id)
    await session.commit()
    return {"removed": removed}


@router.post("/conversations/{conv_id}/messages", response_model=ChatSendOut)
async def send_message(
    conv_id: str,
    body: ChatSend,
    session: AsyncSession = Depends(get_session),
    registry: ModelRegistry = Depends(get_registry),
    bus: EventBus = Depends(get_bus),
    worker: Worker = Depends(get_worker),
) -> ChatSendOut:
    conv = await chat_service.get_conversation(session, conv_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    attachment_meta = chat_attachments.load_attachment_metadata([a.token for a in body.attachments])
    if not body.content.strip() and not attachment_meta:
        raise HTTPException(400, "message content is empty")
    desc = _require_job_type(registry, body.model_id, JobType.LLM)
    if body.image_tool:
        if not body.image_model_id:
            raise HTTPException(400, "image_model_id is required when image_tool is enabled")
        _require_job_type(registry, body.image_model_id, JobType.IMAGE)

    previous_history = await chat_service.get_messages(session, conv_id)
    system = (body.system or conv.system or "").strip()
    max_prompt_tokens = max(
        0,
        settings.llama_ctx
        - max(1, min(8192, body.max_tokens))
        - _estimate_history_tokens(
            system=system,
            history=previous_history,
            user_text=body.content,
            attachments=attachment_meta,
        )
        - 512,
    )
    current_content, enriched_attachments = await chat_attachments.build_user_content(
        body.content,
        attachment_meta,
        allow_images=bool(desc.mmproj_path),
        max_context_tokens=max_prompt_tokens,
    )

    # persist the user turn; auto-title a fresh conversation from it
    user_msg = await chat_service.add_message(
        session,
        conv_id,
        role="user",
        content=body.content,
        attachments=enriched_attachments,
    )
    if not conv.title or conv.title == "New chat":
        title_source = body.content.strip() or enriched_attachments[0]["filename"]
        conv.title = title_source[:60]

    # build the full prompt history (system + all turns so far, incl. this one)
    history = [*previous_history, user_msg]
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    for msg in history:
        content = current_content if msg.id == user_msg.id else _history_content(
            msg,
            allow_images=bool(desc.mmproj_path),
        )
        msgs.append({"role": msg.role, "content": content})

    # empty assistant message the worker will fill in as it streams
    assistant_msg = await chat_service.add_message(session, conv_id, role="assistant", content="")

    params: dict = {
        "messages": msgs,
        "temperature": max(0.0, min(2.0, body.temperature)),
        "max_tokens": max(1, min(8192, body.max_tokens)),
        # linkage so the worker can write the reply back to the DB message
        "assistant_message_id": assistant_msg.id,
        "conversation_id": conv_id,
    }
    for key in ("top_p", "top_k", "min_p", "repeat_penalty", "seed", "stop"):
        value = getattr(body, key)
        if value is not None:
            params[key] = value
    if body.image_tool:
        params["image_tool"] = {
            "model_id": body.image_model_id,
            "conversation_id": conv_id,
            "assistant_message_id": assistant_msg.id,
        }
    if body.document_tool:
        params["document_tool"] = {
            "conversation_id": conv_id,
            "assistant_message_id": assistant_msg.id,
            "top_k": max(1, min(20, int(body.rag_top_k or 5))),
        }
    tools = _chat_tools(body)
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
        params["tool_fallback_systems"] = [
            prompt for enabled, prompt in (
                (body.image_tool, IMAGE_TOOL_SYSTEM),
                (body.document_tool, DOCUMENT_TOOL_SYSTEM),
            )
            if enabled
        ]

    job = await queue_service.create_job(
        session, JobCreate(type=JobType.LLM, model_id=body.model_id, params=params)
    )
    assistant_msg.job_id = job.id

    # persist the chosen settings on the conversation for next time
    conv.model_id = body.model_id
    if system:
        conv.system = system
    conv.params = {
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
        **{k: getattr(body, k) for k in ("top_p", "top_k", "min_p", "repeat_penalty", "stop") if getattr(body, k) is not None},
        "image_tool": bool(body.image_tool),
        **({"image_model_id": body.image_model_id} if body.image_model_id else {}),
        "document_tool": bool(body.document_tool),
        "rag_top_k": max(1, min(20, int(body.rag_top_k or 5))),
    }
    await chat_service.touch(session, conv_id)
    await session.commit()

    bus.emit(EventType.JOB_CREATED, job_id=job.id, job_type=job.type.value)
    worker.notify()
    return ChatSendOut(
        job_id=job.id,
        conversation=ConversationOut.model_validate(conv),
        user_message=MessageOut.model_validate(user_msg),
        assistant_message=MessageOut.model_validate(assistant_msg),
    )


@router.post("/conversations/{conv_id}/image", response_model=ChatSendOut)
async def send_image(
    conv_id: str,
    body: ImageChatSend,
    session: AsyncSession = Depends(get_session),
    registry: ModelRegistry = Depends(get_registry),
    bus: EventBus = Depends(get_bus),
    worker: Worker = Depends(get_worker),
) -> ChatSendOut:
    """Generate an image from inside a chat (the /image bridge). Queues an image
    job on the shared arbiter; the worker writes the result back into the
    assistant message as markdown so it renders inline."""
    conv = await chat_service.get_conversation(session, conv_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not body.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    _require_job_type(registry, body.model_id, JobType.IMAGE)

    user_msg = await chat_service.add_message(session, conv_id, role="user", content=f"/image {body.prompt.strip()}")
    if not conv.title or conv.title == "New chat":
        conv.title = body.prompt.strip()[:60]
    assistant_msg = await chat_service.add_message(session, conv_id, role="assistant", content="")

    params: dict = {"prompt": body.prompt.strip(), "assistant_message_id": assistant_msg.id, "conversation_id": conv_id}
    for key in ("negative", "steps", "width", "height", "seed"):
        value = getattr(body, key)
        if value is not None:
            params[key] = value

    job = await queue_service.create_job(
        session, JobCreate(type=JobType.IMAGE, model_id=body.model_id, params=params)
    )
    assistant_msg.job_id = job.id
    await chat_service.touch(session, conv_id)
    await session.commit()

    bus.emit(EventType.JOB_CREATED, job_id=job.id, job_type=job.type.value)
    worker.notify()
    return ChatSendOut(
        job_id=job.id,
        conversation=ConversationOut.model_validate(conv),
        user_message=MessageOut.model_validate(user_msg),
        assistant_message=MessageOut.model_validate(assistant_msg),
    )
