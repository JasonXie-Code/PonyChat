import asyncio

from Backend.chat_modules import state
from Backend.routes.chat import cancel_generation
from Backend.websocket import generation_locker


async def _reset_generation_state() -> None:
    async with generation_locker.global_lock:
        generation_locker.locks.clear()
    state.cancelled_generation_keys.clear()
    state._generation_versions.clear()


def test_normal_user_interrupt_releases_scheduled_followup_lock():
    async def run():
        await _reset_generation_state()
        try:
            acquired, holder = await generation_locker.try_acquire(
                "user_interrupts_proactive",
                "char_proactive",
                "scheduled_followup",
            )
            assert acquired is True
            assert holder is None

            response = await cancel_generation(
                {
                    "username": "user_interrupts_proactive",
                    "character_id": "char_proactive",
                    "conversation_id": "conv1",
                    "client_id": "single",
                    "reason": "normal_user_interrupt_proactive",
                },
                x_client_id="single",
            )

            assert response["released"] is True
            assert response["released_holder"] == "scheduled_followup"
            assert response["interrupted_proactive"] is True
            locked, lock_holder = await generation_locker.is_locked(
                "user_interrupts_proactive",
                "char_proactive",
            )
            assert locked is False
            assert lock_holder is None
            assert state.is_generation_cancelled(
                "user_interrupts_proactive",
                "char_proactive",
                "scheduled_followup",
            )
        finally:
            await _reset_generation_state()

    asyncio.run(run())


def test_normal_user_interrupt_does_not_release_unrelated_client_lock():
    async def run():
        await _reset_generation_state()
        try:
            acquired, holder = await generation_locker.try_acquire(
                "user_interrupts_proactive",
                "char_other_client",
                "other_client",
            )
            assert acquired is True
            assert holder is None

            response = await cancel_generation(
                {
                    "username": "user_interrupts_proactive",
                    "character_id": "char_other_client",
                    "conversation_id": "conv1",
                    "client_id": "single",
                    "reason": "normal_user_interrupt_proactive",
                },
                x_client_id="single",
            )

            assert response["released"] is False
            assert response["released_holder"] is None
            assert response["interrupted_proactive"] is False
            locked, lock_holder = await generation_locker.is_locked(
                "user_interrupts_proactive",
                "char_other_client",
            )
            assert locked is True
            assert lock_holder == "other_client"
            assert not state.is_generation_cancelled(
                "user_interrupts_proactive",
                "char_other_client",
                "other_client",
            )
        finally:
            await _reset_generation_state()

    asyncio.run(run())


def test_normal_user_interrupt_does_not_cancel_foreground_normal_lock():
    async def run():
        await _reset_generation_state()
        try:
            acquired, holder = await generation_locker.try_acquire(
                "user_interrupts_proactive",
                "char_foreground_normal",
                "single",
            )
            assert acquired is True
            assert holder is None

            response = await cancel_generation(
                {
                    "username": "user_interrupts_proactive",
                    "character_id": "char_foreground_normal",
                    "conversation_id": "conv1",
                    "client_id": "single",
                    "reason": "normal_user_interrupt_proactive",
                },
                x_client_id="single",
            )

            assert response["released"] is False
            assert response["released_holder"] is None
            assert response["interrupted_proactive"] is False
            locked, lock_holder = await generation_locker.is_locked(
                "user_interrupts_proactive",
                "char_foreground_normal",
            )
            assert locked is True
            assert lock_holder == "single"
            assert not state.is_generation_cancelled(
                "user_interrupts_proactive",
                "char_foreground_normal",
                "single",
            )
        finally:
            await _reset_generation_state()

    asyncio.run(run())
