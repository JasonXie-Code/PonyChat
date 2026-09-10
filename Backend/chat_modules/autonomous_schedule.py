"""Validated scheduling plans persisted in the same transaction as the reply."""
import json
import re
import time
import uuid
from .harness_runtime import HarnessToolValidationError

SCHEDULE_SCHEMA = {'type':'object','properties':{
    'kind':{'type':'string','enum':['agreed','followup']},
    'source_message_id':{'type':'string','maxLength':256},
    'summary':{'type':'string','minLength':1,'maxLength':400},
    'task_type':{'type':'string','enum':['reminder','timer','appointment','custom']},
    'schedule_type':{'type':'string','enum':['once','interval','daily','weekly','monthly']},
    'target_delay_seconds':{'type':'integer','minimum':1,'maximum':2592000},
    'interval_seconds':{'type':'integer','minimum':1,'maximum':2592000},
    'time_of_day':{'type':'string','maxLength':5,'description':'HH:MM，00:00到23:59'},
    'days':{'type':'array','maxItems':31,'items':{'type':'integer','minimum':0,'maximum':31}},
    'expires_seconds':{'type':'integer','minimum':1,'maximum':2592000},
    'reason':{'type':'string','maxLength':400}},'required':['kind','summary','source_message_id'],
    'additionalProperties':False}


def validate_schedule(arguments, request, history):
    from .. import scheduled_followup as old
    from .autonomous_contracts import user_batch
    mid = arguments['source_message_id']
    batch = user_batch(history)
    if not any(m.get('message_id')==mid for m in batch) or mid == getattr(request,'_normal_internal_trigger_message_id',None):
        raise HarnessToolValidationError('调度必须引用本轮原始用户消息，内部触发不是新的用户约定')
    data = {**arguments, 'enabled':True}
    if data.get('time_of_day') and not re.fullmatch(r'([01][0-9]|2[0-3]):[0-5][0-9]', data['time_of_day']):
        raise HarnessToolValidationError('time_of_day must be HH:MM, 00:00..23:59')
    if arguments['kind']=='agreed':
        data['cancel_if_user_replies'] = False
        plan = old.coerce_user_agreed_task(data)
        if plan.get('schedule_type') in ('weekly','monthly') and not plan.get('days'):
            raise HarnessToolValidationError('周期提醒须提供具体星期或日期')
    else:
        latest = '\n'.join(m.get('content','') for m in batch)
        if old._is_user_conversation_end(latest):
            raise HarnessToolValidationError('用户已结束对话，不安排主动追发')
        data.update(seed=arguments['summary'], cancel_if_user_replies=True,
                    allow_reschedule_after_send=False, pressure_level='low')
        plan = old.coerce_scheduled_followup(data, is_new_contact_opening=bool(getattr(request,'_is_new_contact_opening',False)))
    if not plan.get('enabled'):
        raise HarnessToolValidationError('缺少有效调度时间或当前状态不允许创建任务')
    return {'kind':arguments['kind'],'source_message_id':mid,'plan':plan,'id':('pt_' if arguments['kind']=='agreed' else 'sf_')+uuid.uuid4().hex}


def persist_schedules(conn, business):
    from .. import scheduled_followup as old
    from ..proactive_settings import apply_frequency_to_delay_seconds
    request = business.request
    now = int(time.time()*1000)
    for item in business.schedules:
        plan = item['plan']
        source = conn.execute("SELECT message_id FROM messages WHERE conversation_id=? AND role='assistant' "
            "AND deleted_at IS NULL AND COALESCE(is_hidden,0)=0 ORDER BY timestamp DESC,rowid DESC LIMIT 1",
            (request.conversation_id,)).fetchone()
        if not source:
            raise RuntimeError('Scheduled task requires its saved assistant reply')
        if item['kind']=='agreed':
            metadata = {'created_from':'normal_chat_agent','user_agreed_task':plan,
                        'user_source_message_id':item['source_message_id']}
            conn.execute('''INSERT INTO proactive_tasks(id,username,character_id,conversation_id,source_message_id,
                title,task_type,schedule_type,source,status,due_at_ms,interval_seconds,time_of_day,timezone,days_json,
                jitter_minutes,prompt,style,cancel_if_user_replies,metadata_json,created_at_ms,updated_at_ms)
                VALUES(?,?,?,?,?,?,?,?, 'user','active',?,?,?,'Asia/Shanghai',?,0,?,'gentle',0,?,?,?)''',
                (item['id'],request.username,request.character_id,request.conversation_id,source[0],
                 plan['summary'][:48],plan['task_type'],plan['schedule_type'],old._next_due_for_agreed_task(plan,now),
                 plan.get('interval_seconds') or plan['target_delay_seconds'],plan['time_of_day'],json.dumps(plan['days']),
                 '按用户约定自然提醒：'+plan['summary'],json.dumps(metadata,ensure_ascii=False),now,now))
        else:
            delay = max(old.MIN_DELAY_SECONDS,min(old.MAX_DELAY_SECONDS,
                apply_frequency_to_delay_seconds(plan['target_delay_seconds'],business.settings.frequency)))
            expires = max(delay,min(old.MAX_EXPIRES_SECONDS,
                apply_frequency_to_delay_seconds(plan['expires_seconds'],business.settings.frequency)))
            conn.execute("UPDATE scheduled_followups SET status='cancelled',cancel_reason='replaced_by_new_assistant_reply',updated_at_ms=? "
                "WHERE username=? AND character_id=? AND conversation_id=? AND status='pending'",
                (now,request.username,request.character_id,request.conversation_id))
            conn.execute('''INSERT INTO scheduled_followups(id,username,character_id,conversation_id,source_message_id,
                status,due_at_ms,expires_at_ms,cancel_if_user_replies,allow_reschedule_after_send,seed,reason,
                pressure_level,chain_id,chain_count,planner_json,created_at_ms,updated_at_ms)
                VALUES(?,?,?,?,?,'pending',?,?,1,0,?,?,'low',?,?,?,?,?)''',
                (item['id'],request.username,request.character_id,request.conversation_id,source[0],
                 now+delay*1000,now+expires*1000,plan['seed'],plan['reason'],
                 getattr(request,'_scheduled_followup_chain_id','') or item['id'],
                 getattr(request,'_scheduled_followup_chain_count',0),json.dumps({'scheduled_followup':plan},ensure_ascii=False),now,now))
