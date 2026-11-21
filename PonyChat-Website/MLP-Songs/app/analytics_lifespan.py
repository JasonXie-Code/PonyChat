"""Serve the recording directory promptly; warm strictly admitted readers separately."""
import asyncio
from contextlib import asynccontextmanager
import logging
from analytics_store import DB_PATH
from analytics_traffic import collect
from music_data import load_index
from validation_heap import trim_validation_heap


async def import_loop():
    while True:
        try:
            await asyncio.to_thread(collect, DB_PATH)
        except Exception:
            logging.getLogger(__name__).exception('Music traffic import failed; retrying')
        await asyncio.sleep(30)


async def warm_readers(app):
    logger = logging.getLogger('uvicorn.error')
    try:
        await _warm_readers()
    except Exception:
        app.state.follow_warm_error = True
        logger.exception('Music reader warmup failed; full readiness remains unavailable')
    finally:
        app.state.follow_warming = False


async def _warm_readers():
    catalog = await asyncio.to_thread(load_index)
    if not catalog.get('songs'):
        raise RuntimeError('Music catalog became unavailable during reader warmup')
    logging.getLogger('uvicorn.error').info('Validated music catalog warmed: %s songs', len(catalog['songs']))
    if any(song.get('followId') for song in catalog['songs']):
        from follow_response_cache import warm_follow_responses
        import music_data
        await asyncio.to_thread(warm_follow_responses, catalog, music_data.DATA, music_data.FOLLOW)
    del catalog
    trim_validation_heap()


@asynccontextmanager
async def lifespan(app):
    # A broken recording index still prevents startup. An expensive follow proof
    # must not prevent ordinary browsing or audio playback during startup.
    basic = await asyncio.to_thread(load_index, include_follows=False)
    if not basic.get('songs'):
        raise RuntimeError('Music catalog is empty; refusing to report readiness')
    del basic
    app.state.follow_warming = True
    app.state.follow_warm_error = False
    tasks = [asyncio.create_task(warm_readers(app)), asyncio.create_task(import_loop())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
