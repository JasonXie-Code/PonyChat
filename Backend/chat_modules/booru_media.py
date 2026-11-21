"""Choose playable media rather than a still thumbnail for browser cards."""
import re

from .autonomous_web_search import public_url


def excluded_media(row, url, terms):
    excluded = {term[1:] for term in terms if term.startswith('-')}
    if excluded.intersection(row.get('tags') or []):
        return True
    video = row.get('media_type') == 'video' or bool(re.search(r'\.(webm|mp4)(?:\?|$)', url, re.I))
    motion = video or row.get('animated') is True or 'animated' in (row.get('tags') or [])
    return ('animated' in excluded and motion) or ('video' in excluded and video)


def select_media(representations, animated=False):
    def choose(keys, extensions):
        for key in keys:
            value = representations.get(key)
            if isinstance(value, str) and re.search(r'\.(' + extensions + r')(?:\?|$)', value, re.I):
                url = public_url(value)
                if url:
                    return url
        return None

    # Derpibooru advertises WebM/MP4 derivatives even when no file exists
    # (notably transparent GIFs). Prefer the original animated representation.
    if animated:
        original = choose(('full',), 'gif|webp|png')
        if original:
            return original
    video = choose(('webm', 'mp4', 'large', 'medium', 'full', 'small', 'thumb'), 'webm|mp4')
    if video:
        return video
    if animated:
        motion = choose(('full', 'large', 'medium', 'small'), 'gif|webp|png')
        if motion:
            return motion
    return choose(('large', 'medium', 'full', 'small', 'thumb'), 'jpe?g|png|gif|webp')


def select_preview(representations, original, animated=False):
    """Use a smaller representation without replacing motion with a still.

    Keep original media separately for viewing, download and sharing. Do not
    select speculative video derivatives for GIFs: some advertised URLs 404.
    """
    if re.search(r'\.(webm|mp4)(?:\?|$)', original, re.I):
        extensions = 'webm|mp4'
    elif animated:
        # Resized PNG/WebP representations need not retain animation.
        if not re.search(r'\.gif(?:\?|$)', original, re.I):
            return original
        extensions = 'gif'
    else:
        extensions = 'jpe?g|png|webp|gif'
    for key in ('small', 'medium', 'large'):
        value = representations.get(key)
        if isinstance(value, str) and re.search(r'\.(' + extensions + r')(?:\?|$)', value, re.I):
            url = public_url(value)
            if url:
                return url
    return original
