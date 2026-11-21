"""Exact physical pitch/rest/unpitched source supplement for normal admission.

The projection is mechanical and never an approval. A separate, explicitly
complete Root source decision is required; geometry-only decisions do not admit
this scope. Old sources without unpitched nodes continue their existing gate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

try:
    from .typed_unpitched_source_events_v1 import read_source
except ImportError:
    from typed_unpitched_source_events_v1 import read_source

SCHEMA = "typed-physical-source-audit/v1"
PROJECTION_SCHEMA = "typed-physical-source-projection/v1"
DECISION_SCHEMA = "root-full-physical-source-decision/v1"
SCOPE = "complete-pitch-rest-unpitched-and-unprinted-forward-source"
AUDIT_FIELDS = {"schema", "status", "canonicalSha256", "sourcePDFsha256", "projection",
                "projectionSha256", "rootSourceDecision"}
DECISION_FIELDS = {"schema", "status", "reviewedBy", "approved", "sourcePassed", "sourceReviewScope",
                   "canonicalSha256", "sourcePDFsha256", "projectionSha256", "sourceCounts",
                   "unprintedForwardCount", "actualSourceReviewEvidenceSha256s"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    # Strict serialized types reject Python bool/int equality, NaN and fields
    # that a semantic-source supplement did not actually preserve.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def is_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def has_unpitched(content):
    """Detect actual XML type, independent of any claimed JSON source counts."""
    root = ET.fromstring(content)
    return any(element.tag.rsplit("}", 1)[-1] == "unpitched" for element in root.iter())


def xml_payload(element):
    if element is None:
        return None
    return dict(tag=element.tag, attributes=dict(element.attrib), text=element.text,
                tail=element.tail, children=[xml_payload(child) for child in element])


def projection(content):
    """Project all physical rows and separate forward payloads, never audio time."""
    parsed = read_source(content)
    source = ET.fromstring(content)
    nodes = {node.get("id"): node for node in source.findall("part/measure/note")}
    rows = copy.deepcopy(parsed["rows"])
    for row in rows:
        node = nodes[row["sourceNoteId"]]
        row.update(sourceNoteAttributes=dict(node.attrib),
                   sourceLyrics=[xml_payload(lyric) for lyric in node.findall("lyric")],
                   sourceNotehead=[xml_payload(head) for head in node.findall("notehead")],
                   sourceUnpitchedDisplay=xml_payload(node.find("unpitched")),
                   sourceRestPayload=xml_payload(node.find("rest")),
                   sourceTimeModification=xml_payload(node.find("time-modification")),
                   sourceBeams=[xml_payload(beam) for beam in node.findall("beam")],
                   sourceNotations=[xml_payload(notation) for notation in node.findall("notations")])
    gaps = copy.deepcopy(parsed["sourceGaps"])
    by_key = {(gap["sourcePart"], gap["measure"], gap["sourceNoteIndex"]): gap for gap in gaps}
    require(len(by_key) == len(gaps), "Forward source identity is ambiguous")
    for part in source.findall("part"):
        for measure in part.findall("measure"):
            for index, node in enumerate(measure):
                if node.tag == "forward":
                    key = (part.get("id"), int(measure.get("number")), index)
                    by_key[key].update(sourceNodeKind="forward", sourceForwardPayload=xml_payload(node))
    return dict(schema=PROJECTION_SCHEMA, sourceParserSchema=parsed["schema"], physicalEvents=rows,
                unprintedSourceGaps=gaps, counts=copy.deepcopy(parsed["counts"]),
                physicalEventCount=len(rows), unprintedForwardCount=len(gaps),
                sourceApproved=False, recordingSchedule=False)


def pending_audit(content, source_pdf_sha256):
    """Unsigned producer interface; this output is deliberately inadmissible."""
    require(is_sha(source_pdf_sha256), "Actual source PDF SHA required")
    data = projection(content)
    return dict(schema=SCHEMA, status="pending-root-full-physical-source-review",
                canonicalSha256=hashlib.sha256(content).hexdigest(), sourcePDFsha256=source_pdf_sha256,
                projection=data, projectionSha256=digest(data), rootSourceDecision=None)


def validate(audit, content, *, canonical_sha256, source_pdf_sha256, pitched_notes):
    """Require exact canonical source plus the complete Root source ticket."""
    require(isinstance(audit, dict) and set(audit) == AUDIT_FIELDS and audit.get("schema") == SCHEMA,
            "Explicit typed physical source audit required")
    require(audit["status"] == "root-approved-complete-physical-source",
            "Typed physical source audit is pending")
    actual_sha = hashlib.sha256(content).hexdigest()
    require(is_sha(canonical_sha256) and actual_sha == canonical_sha256 == audit["canonicalSha256"],
            "Typed physical source canonical identity differs")
    require(is_sha(source_pdf_sha256) and source_pdf_sha256 == audit["sourcePDFsha256"],
            "Typed physical source paper identity differs")
    actual = projection(content)
    require(actual["counts"]["unpitched"] > 0, "Typed unpitched supplement has no actual spoken source")
    require(type(pitched_notes) is int and pitched_notes > 0 and pitched_notes == actual["counts"]["pitch"],
            "Legacy pitched denominator changed or includes spoken/rest heads")
    require(encoded(audit["projection"]) == encoded(actual),
            "Physical source row/gap/kind/pitch/rhythm/lyric/connection payload differs from canonical")
    expected_hash = digest(actual)
    require(is_sha(audit["projectionSha256"]) and audit["projectionSha256"] == expected_hash,
            "Typed physical source projection hash differs")
    decision = audit["rootSourceDecision"]
    require(isinstance(decision, dict) and set(decision) == DECISION_FIELDS
            and decision.get("schema") == DECISION_SCHEMA
            and decision.get("status") == "root-approved-full-physical-source"
            and decision.get("reviewedBy") == "/root"
            and decision.get("sourceReviewScope") == SCOPE,
            "Complete Root physical source decision required; geometry-only is insufficient")
    require(decision["approved"] is True and decision["sourcePassed"] is True,
            "Root full physical source approval is pending")
    require(decision["canonicalSha256"] == actual_sha
            and decision["sourcePDFsha256"] == source_pdf_sha256
            and decision["projectionSha256"] == expected_hash,
            "Root full physical source decision refers to another body")
    require(encoded(decision["sourceCounts"]) == encoded(actual["counts"])
            and type(decision["unprintedForwardCount"]) is int
            and decision["unprintedForwardCount"] == actual["unprintedForwardCount"],
            "Root full physical source scope is incomplete")
    evidence = decision["actualSourceReviewEvidenceSha256s"]
    require(isinstance(evidence, list) and evidence and all(is_sha(value) for value in evidence)
            and len(set(evidence)) == len(evidence),
            "Root complete source review evidence is missing or ambiguous")
    return dict(status="validated-root-complete-typed-physical-source-v1", counts=actual["counts"],
                physicalEvents=actual["physicalEventCount"], unprintedForwards=actual["unprintedForwardCount"],
                sourceProjectionSha256=expected_hash, recordingSchedule=False)


def numeric_equal(value, expected):
    return type(value) in (int, float) and math.isfinite(value) and value == expected


def chord_groups(content):
    """Mechanical canonical chord groups, not a source or performance approval."""
    groups, active = [], []

    def finish():
        if len(active) > 1:
            anchor = active[0]
            groups.append(dict(anchorSourceNoteId=anchor["sourceNoteId"], sourcePart=anchor["sourcePart"],
                voice=anchor["voice"], measure=anchor["measure"], beat=anchor["beatInMeasure"],
                durationBeats=anchor["durationBeats"], sourceNoteIds=[row["sourceNoteId"] for row in active]))

    for row in read_source(content)["rows"]:
        if not row["chordTone"]:
            finish()
            active = [row] if row["sourceKind"] == "pitch" else []
        else:
            require(active and row["sourceKind"] == "pitch", "Canonical chord has no pitched anchor")
            require(all(row[field] == active[0][field] for field in
                    ("sourcePart", "voice", "measure", "beatInMeasure", "durationBeats")),
                    "Mixed source voice/onset/duration chord requires a separate layout contract")
            active.append(row)
    finish()
    return dict(schema="canonical-source-chord-groups/v1", canonicalSha256=hashlib.sha256(content).hexdigest(), groups=groups)


def source_slurs(content):
    """Pair literal canonical source slurs; never infer a recording attack."""
    pending, curves = {}, []
    for row in read_source(content)["rows"]:
        for item in row["slurs"]:
            identity = (row["sourcePart"], row["voice"], item.get("number", "1"))
            require(row["sourceKind"] == "pitch", "Unpitched/rest slur endpoints need a separate source contract")
            if item.get("type") == "start":
                require(identity not in pending, "Ambiguous open source slur")
                pending[identity] = row
            elif item.get("type") == "stop":
                start = pending.pop(identity, None)
                require(start is not None and start["sourceQuarter"] <= row["sourceQuarter"], "Source slur has no ordered start")
                curves.append(dict(sourcePart=row["sourcePart"], voice=row["voice"], number=identity[2],
                    fromSourceNoteId=start["sourceNoteId"], toSourceNoteId=row["sourceNoteId"],
                    fromMeasure=start["measure"], toMeasure=row["measure"]))
            else:
                raise ValueError("Unsupported literal source slur type")
    require(not pending, "Source slur is unclosed")
    return dict(schema="canonical-source-slurs/v1", canonicalSha256=hashlib.sha256(content).hexdigest(), curves=curves)


def validate_notation(source, canonical, notation):
    """Ensure the candidate actually displays every reviewed physical node.

    This does not validate pitched audio occurrences; their existing independent
    contract still applies. Unpitched reading is explicitly untimed in v1.
    """
    content = canonical if isinstance(canonical, bytes) else Path(canonical).read_bytes()
    require(isinstance(source, dict), "Typed physical source review must be an object")
    validate(source.get("typedPhysicalSourceAudit"), content,
             canonical_sha256=source.get("canonicalSha256"), source_pdf_sha256=source.get("sourcePDFsha"),
             pitched_notes=source.get("fullPitchAudit", {}).get("pitchedNotes"))
    original = projection(content)
    physical = {row["sourceNoteId"]:row for row in original["physicalEvents"]}
    require(isinstance(notation, dict) and isinstance(notation.get("tokens"), list)
            and isinstance(notation.get("measures"), list), "Complete physical notation tables required")
    groups = chord_groups(content)
    if groups["groups"]:
        require(notation.get("canonicalSha256") == groups["canonicalSha256"]
                and encoded(notation.get("sourceChordGroups")) == encoded(groups),
                "Candidate chord groups differ from actual canonical source")
    curves = source_slurs(content)
    if curves["curves"]:
        require(encoded(notation.get("sourceSlurs")) == encoded(curves),
                "Candidate source slur display ledger differs from canonical")
    require(all(isinstance(measure, dict) and isinstance(measure.get("tokens"), list)
                and all(isinstance(token, dict) for token in measure["tokens"])
                for measure in notation["measures"]), "Physical notation measure/token tables are invalid")
    flat, nested = notation["tokens"], [token for measure in notation["measures"] for token in measure["tokens"]]
    require(len(flat) == len(nested) == len(physical), "Candidate notation drops or fabricates physical nodes")
    by_source, by_display = {}, {}
    for token in flat:
        require(isinstance(token, dict), "Physical notation token must be an object")
        sid = token.get("originalSourceNoteId")
        identity = token.get("id")
        require(isinstance(sid, str) and sid in physical and sid not in by_source
                and type(identity) in (str, int) and str(identity) and str(identity) not in by_display,
                "Candidate physical source/display identity is absent, duplicated or a forward gap")
        row = physical[sid]
        require(token.get("sourcePart") == row["sourcePart"] and type(token.get("measure")) is int
                and token["measure"] == row["measure"] and numeric_equal(token.get("beat"), row["beatInMeasure"])
                and numeric_equal(token.get("durationBeats"), row["durationBeats"]),
                "Candidate source part/measure/beat/duration differs")
        require(token.get("isRest") is row["isRest"] and token.get("isUnpitched", False) is row["isUnpitched"],
                "Candidate source pitch/rest/unpitched kind differs")
        require(type(token.get("chordTone", False)) is bool and token.get("chordTone", False) is row["chordTone"]
                and token.get("voice", "1") == row["voice"] and token.get("staff", "1") == row["staff"],
                "Candidate source chord/voice/staff differs")
        note_type, syllabic = token.get("noteType"), token.get("syllabic")
        require(note_type in (None, "") or isinstance(note_type, str), "Candidate written note type is invalid")
        require(syllabic in (None, "") or isinstance(syllabic, str), "Candidate source syllabic type is invalid")
        require((note_type or None) == row["noteType"] and type(token.get("dots", 0)) is int
                and token.get("dots", 0) == row["dots"] and token.get("lyric") == row["sourceLyric"]
                and (syllabic or None) == row["syllabic"], "Candidate written type/dots/lyric differs")
        for flag, kind in (("tieStart", "start"), ("tieStop", "stop")):
            wanted = any(t.get("type") == kind for t in row["ties"])
            require(token.get(flag, False) is wanted, "Candidate typed source tie flag differs")
        if curves["curves"]:
            require(encoded(token.get("slurs", [])) == encoded(row["slurs"]), "Candidate literal source slurs changed")
        if "sourcePhysicalId" in token:
            require(token["sourcePhysicalId"] == row["sourcePhysicalId"], "Candidate physical glyph identity differs")
        if row["sourceKind"] == "pitch":
            require(token.get("pitch") == row["pitch"], "Candidate absolute source pitch changed")
        else:
            require(token.get("pitch") in (None, ""), "Candidate nonpitched source invented a pitch")
        if row["isUnpitched"]:
            require(token.get("sourcePhysicalId") == row["sourcePhysicalId"] and token.get("token") == "×"
                    and token.get("midi") is None and token.get("sourcePitch") in (None, ""),
                    "Spoken physical head must preserve literal cross and no MIDI/pitch")
            require(all(field in token and token[field] is None for field in ("eventIndex", "time", "endTime"))
                    and token.get("sourceOnlyUntimed") is True and token.get("skipCursorHighlight") is True
                    and token.get("cursorPrimary", False) is False,
                    "Spoken v1 reading must stay explicitly untimed and readonly")
            require("occurrenceEventIndices" not in token or token["occurrenceEventIndices"] == [],
                    "Spoken readonly head cannot invent recording occurrences")
        by_source[sid] = token; by_display[str(identity)] = token
    require(set(by_source) == set(physical), "Candidate lacks exact full physical source scope")
    seen = set()
    for measure in notation["measures"]:
        for token in measure.get("tokens", []):
            identity = str(token.get("id"))
            require(identity in by_display and identity not in seen
                    and type(measure.get("measure")) is int and token.get("measure") == measure["measure"]
                    and encoded(token) == encoded(by_display[identity]), "Candidate flat/nested source payload differs")
            seen.add(identity)
    return dict(status="validated-complete-typed-physical-source-reading-v1", counts=original["counts"],
                physicalTokens=len(flat), spokenUntimedHeads=original["counts"]["unpitched"],
                pitchedAudioOccurrencesValidatedHere=False)
