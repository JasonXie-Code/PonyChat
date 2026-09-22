"""Bounded, explicitly rated Derpibooru candidates ordered by community score."""
import asyncio
import re

import httpx


RATINGS = ('safe', 'suggestive', 'questionable', 'explicit', 'semi-grimdark', 'grimdark', 'grotesque')
# Derpibooru's anonymous API otherwise applies its restrictive default filter.
# This public system filter exposes every site rating; the requested rating tag
# below still limits each search to exactly one rating.
EVERYTHING_FILTER_ID = 56027
MIN_STRICT_STYLE_RESULTS = 3
_STYLE_TAGS = {'vector', 'show accurate'}


async def search_ranked(tags, *, rating, transport=None, g4_pony=False, animated=None,
                        sort='score', page=1, limit=6, browser_media=False):
    # Accept literal tags only; do not allow boolean/filter syntax to undo rating.
    if rating not in RATINGS:
        return []
    if not isinstance(tags, str) or not 1 <= len(tags) <= (340 if g4_pony else 300):
        return []
    terms = [term.strip().lower() for term in tags.split(',') if term.strip()]
    sort_fields = {'score': ('score', 'desc'), 'time': ('created_at', 'desc'), 'random': ('random', 'desc')}
    if sort not in sort_fields or type(page) is not int or page < 1 or type(limit) is not int or limit not in range(1, 25):
        return []
    # Models commonly repeat the requested rating in derpibooru_tags.  The
    # rating parameter is authoritative, so canonicalize that harmless
    # duplicate instead of treating a normal request as an invalid filter.
    terms = [term for term in terms if term != rating]
    if animated is not None:
        terms = [term for term in terms if term != 'animated']
    pattern = r"-?[a-z0-9][a-z0-9 '()_-]{0,79}" if browser_media else r"[a-z0-9][a-z0-9 '()_-]{0,79}"
    if not terms or any(not re.fullmatch(pattern, term)
                        or term.lstrip('-') in RATINGS
                        or re.search(r'\b(or|not|and)\b', term) for term in terms):
        return []
    from .web_image_style import EXCLUDED_TAGS

    async def fetch(search_terms, *, strict_style):
        query = rating + ', ' + ', '.join(search_terms)
        if animated is not None:
            query += ', animated' if animated else ', -animated'
        if g4_pony:
            query += ', ' + ', '.join('-' + tag for tag in sorted(EXCLUDED_TAGS))
        try:
            async with httpx.AsyncClient(transport=transport, trust_env=False,
                    timeout=6, follow_redirects=False) as client:
                async with client.stream('GET', 'https://derpibooru.org/api/v1/json/search/images',
                        params={'q': query, 'filter_id': EVERYTHING_FILTER_ID,
                                'sf': sort_fields[sort][0], 'sd': sort_fields[sort][1],
                                'page': page, 'per_page': limit if browser_media else max(12, limit)},
                        headers={'User-Agent': 'PonyChat/6.0 image-search'}) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_000_000:
                            return []
                    import json
                    data = json.loads(body)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, TypeError, AttributeError, KeyError):
            return []
        results = []
        required_style = {'pony', 'vector', 'show accurate'} if strict_style else {'pony'}
        from .autonomous_web_search import public_url
        for row in data.get('images', []):
            if not isinstance(row, dict) or rating not in row.get('tags', []):
                continue
            row_tags = set(row['tags'])
            is_animated = row.get('animated') is True or 'animated' in row_tags
            if animated is not None and is_animated != animated:
                continue
            if rating == 'safe' and any(tag in row_tags for tag in RATINGS if tag != 'safe'):
                continue
            if g4_pony and (EXCLUDED_TAGS.intersection(row_tags) or not required_style <= row_tags):
                continue
            ident, score = row.get('id'), row.get('score')
            image = public_url((row.get('representations') or {}).get('large'))
            if is_animated:
                reps = row.get('representations') or {}
                image = next((public_url(reps.get(k)) for k in ('large', 'medium', 'full')
                              if isinstance(reps.get(k), str) and re.search(r'\.(gif|webp|png)(?:\?|$)', reps[k], re.I)), None)
            if browser_media:
                from .booru_media import select_media
                image = select_media(row.get('representations') or {}, is_animated)
            if type(ident) is not int or type(score) is not int or not image:
                continue
            if browser_media:
                from .booru_media import excluded_media
                if excluded_media(row, image, terms):
                    continue
            url = f'https://derpibooru.org/images/{ident}'
            results.append({'id': f'derpibooru:{ident}', 'source': 'Derpibooru',
                'title': ', '.join(row['tags'])[:250], 'tags': row['tags'][:80], 'url': url,
                'source_url': url, 'image_url': image, 'score': score, 'rating': rating,
                'engines': ['derpibooru'], 'snippet': '', 'published_at': row.get('created_at'),
                'style_relaxed': not strict_style, 'animated': is_animated,
                'video': bool(re.search(r'\.(webm|mp4)(?:\?|$)', image, re.I))})
            if browser_media:
                from .booru_media import select_preview
                results[-1]['preview_url'] = select_preview(row.get('representations') or {}, image, is_animated)
        if sort == 'score':
            results.sort(key=lambda row: row['score'], reverse=True)
        elif sort == 'time':
            results.sort(key=lambda row: row.get('published_at') or '', reverse=True)
        return results[:limit]

    strict = await asyncio.wait_for(fetch(terms, strict_style=True), 7)
    if not g4_pony or len(strict) >= MIN_STRICT_STYLE_RESULTS:
        return strict
    # Keep the pony identity and all excluded forms.  Only relax the two
    # default visual tags when the strict search yields too few candidates.
    relaxed_terms = [term for term in terms if term not in _STYLE_TAGS]
    if relaxed_terms == terms:
        return strict
    relaxed = await asyncio.wait_for(fetch(relaxed_terms, strict_style=False), 7)
    seen = {row['source_url'] for row in strict}
    return [*strict, *(row for row in relaxed if row['source_url'] not in seen)][:limit]
