"""Read actual MusicXML heads, rests and spoken crosses without conflating them.

This is a source-only parser. A forward is a gap, not a physical rest. Chord
heads retain their shared source onset. No recording times or MIDI estimates
are manufactured for an unpitched symbol.
"""
from fractions import Fraction
import xml.etree.ElementTree as ET


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(text, label):
    try:
        value = Fraction(text)
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError('Invalid source ' + label) from error
    require(value > 0, 'Source ' + label + ' must be positive')
    return value


def read_source(content, exact_coordinates=False):
    """Return typed source rows; optionally preserve exact rational quarter coordinates."""
    score = ET.fromstring(content)
    require(score.tag == 'score-partwise', 'Expected unqualified partwise MusicXML')
    rows, gaps, identities, part_ids = [], [], set(), set()
    for part in score.findall('part'):
        part_id = part.get('id')
        require(part_id and part_id not in part_ids, 'Source part ID is ambiguous')
        part_ids.add(part_id)
        divisions, length, origin, measures = Fraction(1), Fraction(4), Fraction(0), set()
        for measure in part.findall('measure'):
            try:
                mn = int(measure.get('number'))
            except (ValueError, TypeError) as error:
                raise ValueError('Explicit source measure number required') from error
            require(mn > 0 and mn not in measures, 'Source measure ID is ambiguous')
            measures.add(mn)
            beat, extent, prior = Fraction(0), Fraction(0), None
            for source_index, element in enumerate(measure):
                if element.tag == 'attributes':
                    if element.find('divisions') is not None:
                        divisions = number(element.findtext('divisions'), 'divisions')
                    meter = element.find('time')
                    if meter is not None:
                        length = number(meter.findtext('beats'), 'meter numerator') * 4 / number(
                            meter.findtext('beat-type'), 'meter denominator')
                elif element.tag in ('forward', 'backup'):
                    duration = number(element.findtext('duration'), 'gap duration') / divisions
                    if element.tag == 'backup':
                        beat -= duration
                        require(beat >= 0, 'Source backup precedes the measure')
                    else:
                        gap = dict(sourcePart=part_id, measure=mn, beatInMeasure=float(beat),
                            sourceQuarter=float(origin + beat), durationBeats=float(duration),
                            sourceNoteIndex=source_index, isSyntheticGap=True)
                        if exact_coordinates:
                            gap.update(sourceQuarterRational=[(origin + beat).numerator, (origin + beat).denominator],
                                durationBeatsRational=[duration.numerator, duration.denominator],
                                sourceQuarterEndRational=[(origin + beat + duration).numerator,
                                    (origin + beat + duration).denominator])
                        gaps.append(gap)
                        beat += duration
                        extent = max(extent, beat)
                    prior = None
                elif element.tag == 'note':
                    require(element.find('grace') is None, 'Grace timing needs an explicit source contract')
                    sid = element.get('id')
                    require(sid and sid not in identities, 'Physical source note ID is ambiguous')
                    identities.add(sid)
                    kinds = [name for name in ('pitch', 'rest', 'unpitched') if element.find(name) is not None]
                    require(len(kinds) == 1, 'Physical source kind is missing or contradictory')
                    kind = kinds[0]
                    chord = element.find('chord') is not None
                    require(not chord or prior is not None, 'Chord has no preceding head')
                    duration = number(element.findtext('duration'), 'note duration') / divisions
                    onset = prior if chord else beat
                    require(onset + duration <= length, 'Physical source note exceeds the measure')
                    pitch = None
                    if kind == 'pitch':
                        p = element.find('pitch')
                        step = p.findtext('step')
                        try:
                            alter = int(p.findtext('alter', '0'))
                            octave = int(p.findtext('octave'))
                        except (ValueError, TypeError) as error:
                            raise ValueError('Explicit original spelled pitch required') from error
                        require(isinstance(step, str) and len(step) == 1 and step in 'CDEFGAB' and -2 <= alter <= 2
                            and -1 <= octave <= 9, 'Unsupported original spelled pitch')
                        pitch = step + ('#' * alter if alter > 0 else 'b' * -alter) + str(octave)
                    lyric = element.find('lyric')
                    row = dict(sourceNoteId=sid, sourcePhysicalId=sid, sourcePart=part_id,
                        sourceNoteIndex=source_index, measure=mn, beatInMeasure=float(onset),
                        sourceQuarter=float(origin + onset), durationBeats=float(duration),
                        sourceKind=kind, isRest=kind == 'rest', isUnpitched=kind == 'unpitched',
                        pitch=pitch, voice=element.findtext('voice', '1'), staff=element.findtext('staff', '1'),
                        chordTone=chord, noteType=element.findtext('type'), dots=len(element.findall('dot')),
                        sourceLyric='' if lyric is None else ''.join(t.text or '' for t in lyric.findall('text')),
                        syllabic=None if lyric is None else lyric.findtext('syllabic'),
                        lyricExtend=None if lyric is None or lyric.find('extend') is None else
                            dict(lyric.find('extend').attrib),
                        ties=[dict(t.attrib) for t in element.findall('tie')],
                        slurs=[dict(t.attrib) for t in element.findall('notations/slur')])
                    if exact_coordinates:
                        row.update(sourceQuarterRational=[(origin + onset).numerator, (origin + onset).denominator],
                            durationBeatsRational=[duration.numerator, duration.denominator],
                            sourceQuarterEndRational=[(origin + onset + duration).numerator,
                                (origin + onset + duration).denominator])
                    rows.append(row)
                    extent = max(extent, onset + duration)
                    if not chord:
                        prior = onset
                        beat += duration
            require(extent == length, 'Source measure is incomplete')
            origin += length
    require(rows and part_ids, 'Source has no physical notation')
    return dict(schema='typed-physical-source-events/v1', rows=rows, sourceGaps=gaps,
        counts={kind: sum(row['sourceKind'] == kind for row in rows) for kind in ('pitch', 'rest', 'unpitched')},
        recordingSchedule=False, sourceApproved=False)
