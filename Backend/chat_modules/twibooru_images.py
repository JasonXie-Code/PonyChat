"""Bounded Twibooru search normalized to PonyChat image-browser results."""
import asyncio
import json
import re

import httpx

from .autonomous_web_search import public_url
from .derpibooru_images import RATINGS

EVERYTHING_FILTER_ID = 2


async def search_ranked(tags, *, rating, sort='score', page=1, limit=9, transport=None):
    if rating not in RATINGS or sort not in {'score', 'time', 'random'}:
        return []
    if not isinstance(tags, str) or not 1 <= len(tags) <= 300 or page < 1 or limit not in range(1, 25):
        return []
    terms = [term.strip().lower() for term in tags.split(',') if term.strip()]
    terms = [term for term in terms if term != rating]
    if not terms or any(not re.fullmatch(r"-?[a-z0-9][a-z0-9 '()_-]{0,79}", term)
                        or term.lstrip('-') in RATINGS or re.search(r'\b(or|not|and)\b', term) for term in terms):
        return []
    sort_fields = {'score': ('score', 'desc'), 'time': ('created_at', 'desc'), 'random': ('random', 'desc')}
    try:
        async with httpx.AsyncClient(transport=transport, trust_env=False,
                timeout=7, follow_redirects=False) as client:
            response = await client.get('https://twibooru.org/api/v3/search/posts', params={
                'q': rating + ', ' + ', '.join(terms), 'filter_id': EVERYTHING_FILTER_ID,
                'sf': sort_fields[sort][0], 'sd': sort_fields[sort][1],
                'page': page, 'per_page': limit,
            }, headers={'User-Agent': 'PonyChat/6.0 image-browser'})
            response.raise_for_status()
            if len(response.content) > 1_500_000:
                return []
            data = json.loads(response.content)
    except (httpx.HTTPError, asyncio.TimeoutError, ValueError, TypeError, KeyError):
        return []
    results = []
    for row in data.get('posts', []):
        if not isinstance(row, dict) or row.get('hidden_from_users') is True or rating not in row.get('tags', []):
            continue
        if row.get('media_type') not in {'image', 'video'} or not row.get('thumbnails_generated', False):
            continue
        representations = row.get('representations') or {}
        from .booru_media import select_media, select_preview
        image = select_media(representations, row.get('animated') is True or row.get('media_type') == 'video')
        ident, score = row.get('id'), row.get('score')
        if type(ident) is not int or type(score) is not int or not image:
            continue
        from .booru_media import excluded_media
        if excluded_media(row, image, terms):
            continue
        post_url = f'https://twibooru.org/posts/{ident}'
        results.append({'id': f'twibooru:{ident}', 'source': 'Twibooru',
            'title': ', '.join(row['tags'])[:250], 'tags': row['tags'][:80],
            'url': post_url, 'source_url': post_url, 'image_url': image,
            'score': score, 'rating': rating, 'published_at': row.get('created_at'),
            'animated': row.get('animated') is True,
            'video': bool(re.search(r'\.(webm|mp4)(?:\?|$)', image, re.I)),
            'preview_url': select_preview(representations, image, row.get('animated') is True)})
    return results[:limit]
