"""Agent drafts must fit every mobile card before becoming visible memory."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_unified_agent_memory import db, store, commit, WHEN
from unified_memory_test.agent_memory import jobs, service, review, usage
from unified_memory_test.agent_memory.relationship import PAGE_SCHEMA, complete_page, project, set_manual_stage, validate_page
from unified_memory_test.agent_memory.relationship_page_contract import TEXT_LIMITS, ITEM_LIMITS, mobile_length, page_limits


def page():
    return {**{k:'我还在了解你。' for k in TEXT_LIMITS},
            **{k:['绿茶'] for k in ITEM_LIMITS},'relationship_stage':'familiar'}


@pytest.mark.parametrize('field,limit', [*TEXT_LIMITS.items(),*ITEM_LIMITS.items()])
def test_exact_limit_passes_and_one_more_character_rejected(field,limit):
    value=page()
    value[field]='茶'*limit if field in TEXT_LIMITS else ['茶'*limit]
    assert validate_page(value,strict=True)==value
    assert complete_page(value)
    schema=PAGE_SCHEMA['properties'][field]
    assert (schema if field in TEXT_LIMITS else schema['items'])['maxLength']==limit
    if field in TEXT_LIMITS:
        value[field]+='茶'
    else:
        value[field][0]+='茶'
    assert not complete_page(value)
    with pytest.raises(ValueError,match=rf'{field}.*{limit+1}字.*{limit}字'):
        validate_page(value,strict=True)


def test_mobile_emoji_count_and_whitespace():
    value=page(); value['chips']=['😀😀']
    assert mobile_length(value['chips'][0])==4
    assert complete_page(value)
    value['chips']=['😀😀茶']
    with pytest.raises(ValueError,match='5字，最多4字'):
        validate_page(value,strict=True)
    value=page(); value['mood']='  我\n\n很\t安心。  '
    assert validate_page(value,strict=True)['mood']=='我 很 安心。'


@pytest.mark.parametrize('field', list(ITEM_LIMITS))
@pytest.mark.parametrize('invalid', [[],['茶']*5,'茶',[{}],[' ']])
def test_array_shapes_and_item_counts(field,invalid):
    value=page(); value[field]=invalid
    assert not complete_page(value)
    with pytest.raises(ValueError,match=field):
        validate_page(value,strict=True)


def test_chip_row_budget():
    value=page(); value['chips']=['活力四射','亲密默契','信任','安心']
    assert complete_page(value)
    value['chips'][2]='互不服输'
    with pytest.raises(ValueError,match='4字标签最多2条'):
        validate_page(value,strict=True)


def test_invalid_update_does_not_write_and_agent_can_resubmit(db):
    s=store(db); tools=review.ReviewTools(db,{'username':'alice','character_id':'twilight'},s)
    args={'page':page(),'source_message_ids':['m1'],'occurred_at':WHEN}
    first=asyncio.run(tools.stage_relationship(args)); commit(s)
    s=store(db); tools=review.ReviewTools(db,tools.job,s)
    args['page']['mood']='茶'*73
    with pytest.raises(ValueError,match='mood当前73字，最多72字'):
        asyncio.run(tools.stage_relationship(args))
    assert not s._drafts
    assert project(db,'alice','twilight')['relationship_page']['mood']==page()['mood']
    with pytest.raises(ValueError,match='mood'):
        s.stage(kind='fact',category='relationship_page',certainty='inferred',
                content=json.dumps(args['page']),source_message_ids=['m1'],occurred_at=WHEN)
    assert not s._drafts
    args['page']['mood']='想到你喜欢绿茶，我很期待下次聊天。'
    second=asyncio.run(tools.stage_relationship(args)); commit(s)
    assert second['entry_id']==first['entry_id'] and second['version']==2


def test_legacy_read_and_manual_stage_preserve_copy_but_request_rebuild(db):
    value=page(); value['overview']='茶'*120
    service.manual(db,'alice','twilight',category='relationship_page',content=json.dumps(value))
    set_manual_stage(db,'alice','twilight','trusted_companion')
    saved=project(db,'alice','twilight')
    assert saved['relationship_page'] is None
    assert json.loads(store(db).list(category='relationship_page')[0]['content'])['overview']==value['overview']
    assert saved['relationship_stage']=='trusted_companion'
    assert not complete_page(saved['relationship_page'])
    set_manual_stage(db,'alice','pinkie','familiar')
    assert project(db,'alice','pinkie')['relationship_stage']=='familiar'


def test_opening_legacy_page_queues_one_rebuild_without_overwriting_history(db,monkeypatch):
    from Backend import relationship_insights
    value=page(); value['self_portrait']='茶'*60
    service.manual(db,'alice','twilight',category='relationship_page',content=json.dumps(value))
    monkeypatch.setattr(relationship_insights,'get_database',lambda:SimpleNamespace(db_path=db))
    first=asyncio.run(relationship_insights.load_relationship_state('alice','twilight'))
    assert first['generation_status']=='queued'
    revision=jobs.status(db,'alice','twilight')['revision']
    for _ in range(3):
        assert asyncio.run(relationship_insights.load_relationship_state('alice','twilight'))['generation_status']=='queued'
    assert jobs.status(db,'alice','twilight')['revision']==revision
    assert project(db,'alice','twilight')['relationship_page']['self_portrait']==value['self_portrait']


def test_boundary_valid_copy_is_not_truncated_by_mobile_api_formatter():
    from Backend.relationship_insights import normalize_relationship_page_content
    value={**{k:'茶'*limit for k,limit in TEXT_LIMITS.items()},
           **{k:['茶'*limit] for k,limit in ITEM_LIMITS.items()}}
    saved=validate_page(value,strict=True)
    exposed=normalize_relationship_page_content(saved)
    assert all(exposed[k]==value[k] for k in value)


@pytest.mark.parametrize('existing', ['none','valid','overlong'])
def test_every_review_includes_budgets_even_existing_page_updates(db,monkeypatch,existing):
    if existing!='none':
        value=page()
        if existing=='overlong': value['mood']='茶'*100
        service.manual(db,'alice','twilight',category='relationship_page',content=json.dumps(value))
    jobs.enqueue(db,'alice','twilight',immediate=True)
    job=jobs.claim(db,username='alice',character_id='twilight')

    async def runner(raw,*_args,**_kwargs):
        prompt=json.loads(raw)
        assert prompt['relationship_page_limits']==page_limits()
        assert '首次生成和后续更新' in prompt['relationship_page_copy_instruction']
        assert prompt['relationship_page_required']==(existing!='valid')
        return {'finish_reason':'completed','final_response':'{}'}

    async def no_meter(*_args,**_kwargs): pass
    monkeypatch.setattr(review.ReviewTools,'register',lambda _self:{})
    monkeypatch.setattr(usage,'meter_user',no_meter)
    asyncio.run(review.review(db,job,{},'profile',harness_runner=runner))
