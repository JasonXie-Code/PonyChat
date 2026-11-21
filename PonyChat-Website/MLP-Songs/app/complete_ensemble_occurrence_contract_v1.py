"""Exact serializable occurrence edition fields; no previous-profile alias."""
import copy
PROFILE='complete-original-ensemble-occurrence-reading-reference/v1'
def certificate_scope(review):
 if review.get('qualifiedReadingProfile')!=PROFILE:raise ValueError('Explicit occurrence certificate profile required')
 names=('qualifiedReferenceScope','occurrenceEvidence','pitchUnconfirmedOccurrenceIds','recordingLyricUnconfirmedOccurrenceIds',
  'clockQualification','recordingEvidenceQualification','displayLimitations','reviewedRuntimeFrontend')
 result=dict(referenceContractVersion=6,qualifiedReadingProfile=PROFILE,originalReviewInputsSha256=review['reviewInputsSha256'],
  rootDecisionSha256=review['rootDecisionSha256'],**{k:copy.deepcopy(review[k]) for k in names})
 return result


def validate_metadata(version,decision,proposal):
 """Required display/clock qualifications cannot drift from the actual Root proposal."""
 import json
 for key in ('clockQualification','recordingEvidenceQualification','displayLimitations','reviewedRuntimeFrontend'):
  present=[key in body for body in (version,decision,proposal)]
  if not all(present) or any(json.dumps(body[key],sort_keys=True,separators=(',',':'),allow_nan=False)!=json.dumps(version[key],sort_keys=True,separators=(',',':'),allow_nan=False) for body in (decision,proposal)):
   raise ValueError('Occurrence edition metadata missing/differs from actual Root proposal: '+key)
 return True
