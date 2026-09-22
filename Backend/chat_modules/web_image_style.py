"""Default visual identity for pony character image searches."""

from .Prompts import image_style


EXCLUDED_TAGS = {'anthro', 'human', 'humanized', 'equestria girls', '3d', 'g5', 'photorealistic'}


def apply_style(arguments):
    result = dict(arguments)
    if result.get('style') == 'user_requested' or result.get('subject_type') != 'pony':
        return result
    result['query'] = str(result.get('query', ''))[:210] + ' MLP G4 pony show accurate 2D vector -human -anthro -3d -g5'
    if not result.get('derpibooru_tags'):
        return result
    terms = [t.strip() for t in result['derpibooru_tags'].split(',') if t.strip()]
    for tag in ('pony', 'vector', 'show accurate'):
        if tag not in [t.lower() for t in terms]:
            terms.append(tag)
    result['derpibooru_tags'] = ', '.join(terms)
    result['g4_pony'] = True
    return result
