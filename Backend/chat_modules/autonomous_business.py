"""Scoped business decisions owned by the replying Agent."""
from .Prompts import AUTONOMOUS_BUSINESS_TEXT, schedule, lifecycle, handoff
import json
import re
from .harness_runtime import HarnessToolValidationError
from .autonomous_contracts import user_batch


class BusinessTools:
    def __init__(self, request, history, shortcut, settings, candidates):
        self.request, self.history, self.shortcut = request, history, shortcut
        self.settings, self.candidates = settings, candidates
        self.schedules = []
        self.lifecycle = None
        self.followup_decision = None
        self.text = '\n'.join(m.get('content','') for m in user_batch(history))
        self.reminder_expected = bool(settings.enabled
            and not getattr(request, '_normal_internal_proactive_trigger', False)
            and re.search(r'(?:\d+|[零一二两三四五六七八九十百半]+)(?:秒|分钟|小时)后(?:请|记得|帮我)?提醒我', self.text)
            and not re.search(r'如果|假如|假设|不要|不用|取消|不需要', self.text))
        from .normal_lifecycle import is_explicit_character_death_action
        name = getattr(request, '_normal_speaker_character_name', '') or ''
        self.death_expected = (is_explicit_character_death_action(self.text,character_name=name)
            and ('你' in self.text or name and name in self.text)
            and not getattr(request, '_normal_dead_spirit_reply',False))
        self.schedule_guidance = schedule + str(settings.enabled)
        self.lifecycle_guidance = lifecycle
        if getattr(request, '_normal_dead_spirit_reply', False):
            from .Prompts import lifecycle_spirit_rules
            self.lifecycle_guidance += '\n' + lifecycle_spirit_rules
        self.handoff_guidance = handoff + json.dumps(candidates, ensure_ascii=False)

    def register(self, capability):
        preferences = getattr(self.request, '_autonomous_preference_edits', None)
        if preferences:
            preferences.register(capability)
        from .autonomous_schedule import SCHEDULE_SCHEMA
        capability('stage_schedule', AUTONOMOUS_BUSINESS_TEXT['register_1'], SCHEDULE_SCHEMA, self.schedule)
        capability('stage_character_death', AUTONOMOUS_BUSINESS_TEXT['register_2'], {
            'type':'object','properties':{'source_message_id':{'type':'string','maxLength':256},
            'reason':{'type':'string','minLength':1,'maxLength':300}},
            'required':['source_message_id','reason'],'additionalProperties':False}, self.death)
        if self.candidates and getattr(self.request, '_normal_enable_stage3_handoff_events', False):
            capability('handoff_reply', AUTONOMOUS_BUSINESS_TEXT['register_3'], {
                'type':'object','properties':{'reply_character_id':{'type':'string','enum':[r['reply_character_id'] for r in self.candidates]},
                'reason':{'type':'string','minLength':1,'maxLength':300}},
                'required':['reply_character_id','reason'],'additionalProperties':False}, self.handoff)

    async def schedule(self, arguments):
        from .autonomous_schedule import validate_schedule
        if self.lifecycle or getattr(self.request, '_normal_dead_spirit_reply', False):
            raise HarnessToolValidationError(AUTONOMOUS_BUSINESS_TEXT['schedule_2'])
        if not self.settings.enabled:
            raise HarnessToolValidationError(AUTONOMOUS_BUSINESS_TEXT['schedule_3'])
        if arguments['kind'] == 'followup':
            from .autonomous_followup import eligibility
            if eligibility(self):
                raise HarnessToolValidationError('当前不安排追发：' + eligibility(self))
        plan = validate_schedule(arguments, self.request, self.history)
        def identity(item):
            value = item['plan']
            return (item['kind'], item['source_message_id'],
                    re.sub(r'[\s，。,.!?！？]', '', value.get('summary', value.get('seed', ''))),
                    value.get('schedule_type'), value.get('target_delay_seconds'),
                    value.get('interval_seconds'), value.get('time_of_day'), tuple(sorted(value.get('days', []))))
        existing = next((item for item in self.schedules if identity(item) == identity(plan)), None)
        if existing:
            return {'staged': True, 'id': existing['id'], 'kind': existing['kind'], 'already_staged': True,
                    'note': AUTONOMOUS_BUSINESS_TEXT['schedule_4']}
        if len(self.schedules)>=4:
            raise HarnessToolValidationError('每轮最多4个调度草案')
        self.schedules.append(plan)
        return {'staged':True,'id':plan['id'],'kind':plan['kind'],'summary':plan['plan'].get('summary',plan['plan'].get('seed')),
                'note':AUTONOMOUS_BUSINESS_TEXT['schedule_1']}

    def finalize_delivery(self, data):
        from .autonomous_followup import finalize_followup
        error = self.shortcut.delivery_error(data) if self.shortcut.description else ''
        if error:
            raise ValueError(error)
        dead = bool(self.lifecycle or getattr(self.request, '_normal_dead_spirit_reply', False))
        if dead:
            self.schedules.clear()
        if self.reminder_expected and not dead and not any(p['kind'] == 'agreed' for p in self.schedules):
            raise ValueError(AUTONOMOUS_BUSINESS_TEXT['finalize_delivery_1'])
        decision = finalize_followup(self, data)
        # Execution receipts are independent of style and semantic prose review.
        # Internal scheduler instructions are never a fresh user death event.
        if not getattr(self.request, '_normal_internal_proactive_trigger', False):
            if self.death_expected and self.lifecycle is None:
                raise ValueError(AUTONOMOUS_BUSINESS_TEXT['finalize_delivery_2'])
        return decision

    async def death(self, arguments):
        mid = arguments['source_message_id']
        row = next((m for m in user_batch(self.history) if m.get('message_id')==mid), None)
        if row is None or getattr(self.request, '_normal_dead_spirit_reply', False):
            raise HarnessToolValidationError(AUTONOMOUS_BUSINESS_TEXT['death_2'])
        # The model judges actual outcome from original context. A prompt command
        # alone is not evidence; semantic instructions prohibit jokes/hypotheticals.
        if re.search(r'如果|假如|假设|梦到|开玩笑|假死|装死|what if', row.get('content',''), re.I):
            raise HarnessToolValidationError(AUTONOMOUS_BUSINESS_TEXT['death_3'])
        if not re.search(r'死|斩首|爆头|心脏|喉咙|death|died|dead|kill|murder', row.get('content',''), re.I):
            raise HarnessToolValidationError(AUTONOMOUS_BUSINESS_TEXT['death_4'])
        self.lifecycle = dict(arguments)
        cancelled = [item['id'] for item in self.schedules]
        self.schedules.clear()
        return {'staged':True,'state':'dead','cancelled_schedule_ids':cancelled,
                'note':AUTONOMOUS_BUSINESS_TEXT['death_1']}

    async def handoff(self, arguments):
        from .service import _normal_handoff_target_allowed
        from .normal_speaker import effective_speaker_character_id
        if arguments['reply_character_id'] not in {c['reply_character_id'] for c in self.candidates} or not await _normal_handoff_target_allowed(
                self.request, arguments['reply_character_id'], current_reply_id=effective_speaker_character_id(self.request)):
            raise HarnessToolValidationError(AUTONOMOUS_BUSINESS_TEXT['handoff_1'])
        self.request._normal_handoff_router_result = dict(arguments)
        return {'staged':True,**arguments}
