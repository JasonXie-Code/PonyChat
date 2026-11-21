import asyncio
from Backend.chat_modules.model_call_deadline import ModelCallDeadline


def test_each_step_gets_its_own_limit_and_tool_gap_is_excluded():
    async def exercise():
        timer = ModelCallDeadline(.08)
        try:
            for step in (1, 2):
                timer.event('step/start', {'turn': 1, 'step': step})
                await asyncio.sleep(.045)
                assert not timer.expired.is_set()
                timer.event('assistant/message', {'turn': 1, 'step': step})
                await asyncio.sleep(.09)  # Tool gap longer than a model deadline.
                assert not timer.expired.is_set()
        finally:
            timer.close()
    asyncio.run(exercise())


def test_one_silent_step_expires_and_cleanup_cancels_pending_timer():
    async def exercise():
        timer = ModelCallDeadline(.02)
        timer.event('step/start', {'turn': 1, 'step': 1})
        await asyncio.wait_for(timer.expired.wait(), .2)
        timer.close()
        second = ModelCallDeadline(.02)
        second.event('step/start', {'turn': 1, 'step': 1})
        second.close()
        await asyncio.sleep(.04)
        assert not second.expired.is_set()
    asyncio.run(exercise())
