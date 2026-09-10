"""Bounded, explicitly rated Derpibooru candidates ordered by community score."""
import asyncio
import re

import httpx


RATINGS = ('safe', 'suggestive', 'questionable', 'explicit', 'semi-grimdark', 'grimdark', 'grotesque')
# Derpibooru's anonymous API otherwise applies its restrictive default filter.
# This public system filter exposes every site rating; the requested rating tag
# below still limits each search to exactly one rating.
EVERYTHING_FILTER_ID = 56027


async def search_ranked(tags, *, rating, transport=None, g4_pony=False):
    # Accept literal tags only; do not allow boolean/filter syntax to undo rating.
    if rating not in RATINGS:
        return []
    if not isinstance(tags, str) or not 1 <= len(tags) <= (340 if g4_pony else 300):
        return []
    terms = [term.strip().lower() for term in tags.split(',') if term.strip()]
    if not terms or any(not re.fullmatch(r"[a-z0-9][a-z0-9 '()_-]{0,79}", term)
                        or term in RATINGS
                        or re.search(r'\b(or|not|and)\b', term) for term in terms):
        return []
    from .web_image_style import EXCLUDED_TAGS
    query = rating + ', ' + ', '.join(terms)
    if g4_pony:
        query += ', ' + ', '.join('-' + tag for tag in sorted(EXCLUDED_TAGS))
    async def fetch():
        async with httpx.AsyncClient(transport=transport, trust_env=False,
                timeout=6, follow_redirects=False) as client:
            async with client.stream('GET', 'https://derpibooru.org/api/v1/json/search/images',
                    params={'q': query, 'filter_id': EVERYTHING_FILTER_ID, 'sf': 'score',
                            'sd': 'desc', 'per_page': 12},
                    headers={'User-Agent': 'PonyChat/6.0 image-search'}) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_000_000:
                        return {}
                import json
                return json.loads(body)
    try:
        data = await asyncio.wait_for(fetch(), 7)
        results = []
        from .autonomous_web_search import public_url
        for row in data.get('images', []):
            if not isinstance(row, dict) or rating not in row.get('tags', []):
                continue
            if rating == 'safe' and any(tag in row['tags'] for tag in RATINGS if tag != 'safe'):
                continue
            if g4_pony and (EXCLUDED_TAGS.intersection(row['tags']) or
                            not {'pony', 'vector', 'show accurate'} <= set(row['tags'])):
                continue
            ident, score = row.get('id'), row.get('score')
            image = public_url((row.get('representations') or {}).get('large'))
            if type(ident) is not int or type(score) is not int or not image:
                continue
            url = f'https://derpibooru.org/images/{ident}'
            results.append({'title': ', '.join(row['tags'])[:250], 'url': url,
                'source_url': url, 'image_url': image, 'score': score, 'rating': rating,
                'engines': ['derpibooru'], 'snippet': '', 'published_at': row.get('created_at')})
        return sorted(results, key=lambda row: row['score'], reverse=True)[:6]
    except (httpx.HTTPError, asyncio.TimeoutError, ValueError, TypeError, AttributeError, KeyError):
        return []
