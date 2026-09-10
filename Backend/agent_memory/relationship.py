"""Relationship UI is a live projection of source-validated Agent understanding."""
import json
from datetime import datetime
from contextlib import closing
from .schema import connect
from .store import list_entries
from .relationship_page_contract import FIELDS, LIST_FIELDS, page_properties, validate_copy
from .relationship_control import control, effective_decision, read_control, set_control

DECISION_FIELDS=('relationship_stage','character_intimacy_style','requested_escalation','user_pressure_level')
DECISION_ENUMS={
    'relationship_stage':('new_contact','uncertain','familiar','mentor_student','trusted_companion','family_like',
        'flirting','committed_partner','intimate_partner','broken_up','in_conflict','mutual_dislike','hurtful_dynamic'),
    'character_intimacy_style':('cautious','balanced','playful','open'),
    'requested_escalation':('none','affection','flirting','physical_intimacy','sexual_intimacy',
        'dominance_identity','long_term_commitment','biography_rewrite','world_rewrite'),
    'user_pressure_level':('low','medium','high'),
}
DECISION_DEFAULTS={'relationship_stage':'uncertain','character_intimacy_style':'balanced',
                   'requested_escalation':'none','user_pressure_level':'low'}
PAGE_SCHEMA={'type':'object','properties':{
    **page_properties(),
    'relationship_stage':{'type':'string','enum':list(DECISION_ENUMS['relationship_stage'])}},
    'required':[*FIELDS,*LIST_FIELDS,'relationship_stage'],'additionalProperties':False}
PAGE_SCHEMA['properties']['self_portrait']['description']+='界面标题是她眼中的你：仅写角色眼中的用户性格或状态，不能写角色自我介绍、职业、种族。未知时写我还在了解你的习惯。'
PAGE_SCHEMA['properties']['remembered_items']['description']+='有原文依据的小事；一次玩笑只记为一次互动，不得概括成用户长期喜好、性格或爱好。'

def complete_page(page):
    try:
        validate_copy(page)
        return True
    except ValueError:
        return False

def validate_page(value, *, strict=False):
    if not isinstance(value,dict):
        raise ValueError('Relationship page must be an object')
    if strict:
        return {**validate_copy(value),'relationship_stage':normalize_decision(value)['relationship_stage']}
    result={k:str(value.get(k) or '')[:1500] for k in FIELDS}
    for k in LIST_FIELDS:
        items=value.get(k,[])
        if not isinstance(items,list) or any(not isinstance(v,str) for v in items):
            raise ValueError(k+' must be an array of text')
        result[k]=items[:10]
    result['relationship_stage']=normalize_decision(value)['relationship_stage']
    return result


def normalize_decision(value, *, strict=False):
    source=value if isinstance(value,dict) else {}
    result={}
    for field,allowed in DECISION_ENUMS.items():
        candidate=str(source.get(field) or DECISION_DEFAULTS[field]).strip().lower()
        if candidate not in allowed:
            if strict:
                raise ValueError('Invalid '+field)
            candidate=DECISION_DEFAULTS[field]
        result[field]=candidate
    return result


def stage_agent_decision(store, decision, *, source_message_ids, occurred_at):
    """Stage the foreground Agent's relation fields as their own evidence record."""
    state=normalize_decision(decision,strict=True)
    if store is None:
        return {'relationship_state':state,'changed':True,'staged':False}
    effective = effective_decision(state, control(store.path, store.username, store.character_id))
    existing=store.list(category='relationship_state',include_stale=True,limit=1)
    previous=DECISION_DEFAULTS
    update={}
    if existing:
        try:
            previous=normalize_decision(json.loads(existing[0]['content']))
        except (ValueError,TypeError):
            previous=DECISION_DEFAULTS
        update={'entry_id':existing[0]['entry_id'],'expected_version':existing[0]['version']}
    if existing and previous==state:
        return {'relationship_state':effective,'changed':False,'staged':False}
    draft=store.stage(kind='fact',category='relationship_state',certainty='inferred',
        content=json.dumps(state,ensure_ascii=False),source_message_ids=source_message_ids,
        occurred_at=occurred_at,**update)
    return {'relationship_state':effective,'changed':True,'staged':True,
            'entry_id':draft['entry_id'],'version':draft['version']}

def project(path,username,character_id):
    with closing(connect(path)) as conn:
        page_rows=list_entries(conn,username,character_id,category='relationship_page',limit=1)
        state_rows=list_entries(conn,username,character_id,category='relationship_state',limit=1)
        selection=read_control(conn,username,character_id)
    if not page_rows and not state_rows and not selection['updated_at_ms']:
        return None
    row=page_rows[0] if page_rows else None
    try:
        page=validate_page(json.loads(row['content'])) if row else validate_page({})
        decision=(normalize_decision(json.loads(state_rows[0]['content'])) if state_rows
                  else normalize_decision(page))
    except (ValueError,TypeError):
        if selection['mode'] != 'manual':
            return None
        # Malformed historical inference must never suppress a user's selection.
        row=None
        page=validate_page({})
        decision=normalize_decision({})
    source_row=state_rows[0] if state_rows else row
    page_time=int(datetime.fromisoformat(row['created_at']).timestamp()*1000) if row else 0
    decision=effective_decision(decision,selection)
    page['relationship_stage']=decision['relationship_stage']
    return {'username':username,'character_id':character_id,
            'conversation_id':source_row['origin_conversation_id'] if source_row else '',
            **decision,'relationship_page':page if page_time>selection['updated_at_ms'] else None,
            'relationship_mode':selection['mode'],
            'manual_relationship_stage':selection['stage'],
            'relationship_page_source':({'engine':'agent-memory','entry_id':row['entry_id'],'version':row['version']}
                                        if row else None),
            'relationship_state_source':({'engine':'foreground-agent','entry_id':state_rows[0]['entry_id'],
                                          'version':state_rows[0]['version']} if state_rows else None),
            'relationship_page_updated_at_ms':page_time,
            'updated_at_ms':max(selection['updated_at_ms'],
                int(datetime.fromisoformat(source_row['created_at']).timestamp()*1000) if source_row else 0)}


def set_manual_stage(path,username,character_id,stage):
    set_control(path,username,character_id,'manual',stage)
