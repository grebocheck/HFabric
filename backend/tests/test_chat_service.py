from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.db.models import Conversation, Message
from app.db.session import init_db, session_scope
from app.services import chat_service


@pytest.fixture
async def chat_db():
    await init_db()
    async with session_scope() as s:
        await s.execute(delete(Message))
        await s.execute(delete(Conversation))
    yield
    async with session_scope() as s:
        await s.execute(delete(Message))
        await s.execute(delete(Conversation))


async def test_conversation_crud_and_list_order(chat_db):
    async with session_scope() as s:
        old = await chat_service.create_conversation(s, title="Old", model_id="m1", params={"temperature": 0.1})
        old.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
        new = await chat_service.create_conversation(s, title="New", system="sys")
        new.updated_at = datetime(2026, 1, 2, tzinfo=UTC)

    async with session_scope() as s:
        listed = await chat_service.list_conversations(s)
        assert [conv.id for conv in listed] == [new.id, old.id]
        assert (await chat_service.get_conversation(s, old.id)).title == "Old"

        updated = await chat_service.update_conversation(
            s,
            old.id,
            title="Renamed",
            model_id=None,
            params={"top_p": 0.8},
            does_not_exist="ignored",
        )
        assert updated.title == "Renamed"
        assert updated.model_id == "m1"
        assert updated.params == {"top_p": 0.8}

        assert await chat_service.update_conversation(s, "missing", title="x") is None
        assert await chat_service.delete_conversation(s, "missing") is False
        assert await chat_service.delete_conversation(s, new.id) is True

    async with session_scope() as s:
        assert await chat_service.get_conversation(s, new.id) is None


async def test_messages_truncate_touch_and_finalize(chat_db):
    async with session_scope() as s:
        conv = await chat_service.create_conversation(s)
        first = await chat_service.add_message(s, conv.id, role="user", content="first")
        assistant = await chat_service.add_message(
            s,
            conv.id,
            role="assistant",
            content="",
            job_id="job1",
            attachments=[{"token": "t"}],
        )
        last = await chat_service.add_message(s, conv.id, role="user", content="last")

        base = datetime(2026, 1, 1, tzinfo=UTC)
        first.created_at = base
        assistant.created_at = base + timedelta(seconds=1)
        last.created_at = base + timedelta(seconds=2)

    async with session_scope() as s:
        messages = await chat_service.get_messages(s, conv.id)
        assert [message.content for message in messages] == ["first", "", "last"]
        assert messages[1].attachments == [{"token": "t"}]

        await chat_service.finalize_assistant_message(s, assistant.id, "done", error=True)
        finalized = await s.get(Message, assistant.id)
        assert finalized.content == "done"
        assert finalized.error is True
        assert finalized.job_id is None

        before_touch = (await s.get(Conversation, conv.id)).updated_at
        await chat_service.touch(s, conv.id)
        assert (await s.get(Conversation, conv.id)).updated_at >= before_touch

        assert await chat_service.truncate_from(s, conv.id, assistant.id) == 2
        assert await chat_service.truncate_from(s, "other", first.id) == 0
        assert await chat_service.truncate_from(s, conv.id, "missing") == 0

    async with session_scope() as s:
        remaining = await chat_service.get_messages(s, conv.id)
        assert [message.id for message in remaining] == [first.id]


async def test_finalize_missing_message_is_noop(chat_db):
    async with session_scope() as s:
        await chat_service.finalize_assistant_message(s, "missing", "ignored", error=True)
