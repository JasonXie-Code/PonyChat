"""Signed complete-source public routing; unknown profiles never become typed-X."""
try:
    from .sealed_complete_ensemble_reading_v1 import PROFILE
except ImportError:
    from sealed_complete_ensemble_reading_v1 import PROFILE
TYPED_PROFILE='typed-unpitched-common-source-reading-reference/v1'
OCCURRENCE_PROFILE='complete-original-ensemble-occurrence-reading-reference/v1'

def module(meta):
    if meta.get('qualifiedReadingProfile')==OCCURRENCE_PROFILE:
        try:
            from . import sealed_complete_ensemble_occurrence_reading_v1 as actual
        except ImportError:
            import sealed_complete_ensemble_occurrence_reading_v1 as actual
    elif meta.get('qualifiedReadingProfile')==TYPED_PROFILE:
        try:
            from . import sealed_typed_unpitched_reading_v1 as actual
        except ImportError:
            import sealed_typed_unpitched_reading_v1 as actual
    else:
        try:
            from . import sealed_complete_ensemble_reading_v1 as actual
        except ImportError:
            import sealed_complete_ensemble_reading_v1 as actual
    return actual

def consistent(meta,sync):
    if meta.get('qualifiedReadingProfile')==OCCURRENCE_PROFILE or sync.get('qualifiedReadingProfile')==OCCURRENCE_PROFILE:
        if meta.get('qualifiedReadingProfile')!=sync.get('qualifiedReadingProfile'):
            raise ValueError('One-sided occurrence public profile')
    if meta.get('qualifiedReadingProfile')==TYPED_PROFILE or sync.get('qualifiedReadingProfile')==TYPED_PROFILE:
        if meta.get('qualifiedReadingProfile')!=sync.get('qualifiedReadingProfile'):
            raise ValueError('One-sided typed normal public profile')

def opted(meta,sync):
    consistent(meta,sync)
    return module(meta).opted(meta,sync)
def validate(meta,*args):
    consistent(meta,args[2])
    return module(meta).validate(meta,*args)
def response(meta,*args):
    consistent(meta,args[2])
    return module(meta).response(meta,*args)
