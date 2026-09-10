"""Scoped business decisions owned by the replying Agent."""
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
        self.guidance = shortcut.guidance + '\n' + (
            '【本轮业务操作】\n'
            '1. 用户本轮明确约定提醒，且调度可用时，调用stage_schedule暂存；成功返回后才可承诺安排。\n'
            '2. 角色有可独立补充的新内容且调度允许时，用followup安排稍后续接；用户明确结束时不追发，不把尚未回复当作同意或行动。\n'
            '3. 收到内部主动触发指令时，只执行对应任务，不将该指令保存为用户事实。\n'
            '4. 角色本轮实际发生终局死亡时，调用stage_character_death；假设、玩笑、假死、替身或未遂不记录为死亡。\n'
            '5. 需要其他在场角色接话时，调用handoff_reply，只能选择服务器提供的候选。\n'
            '调度可用：' + str(settings.enabled) + '\n角色候选：' + json.dumps(candidates, ensure_ascii=False))
        if getattr(request, '_normal_dead_spirit_reply', False):
            from .normal_nonstream import NORMAL_DEAD_SPIRIT_STAGE3_GUARD
            self.guidance += '\n' + NORMAL_DEAD_SPIRIT_STAGE3_GUARD

    def register(self, capability):
        preferences = getattr(self.request, '_autonomous_preference_edits', None)
        if preferences:
            preferences.register(capability)
        from .autonomous_schedule import SCHEDULE_SCHEMA
        capability('stage_schedule', '暂存用户约定提醒或有新内容的延迟追发，与回复一起落库。同一提醒成功暂存一次即可，重复调用不会新增相同任务。', SCHEDULE_SCHEMA, self.schedule)
        capability('stage_character_death', '记录本轮当前角色真正发生的终局死亡。须引用本轮原始用户消息并说明判断。', {
            'type':'object','properties':{'source_message_id':{'type':'string','maxLength':256},
            'reason':{'type':'string','minLength':1,'maxLength':300}},
            'required':['source_message_id','reason'],'additionalProperties':False}, self.death)
        if self.candidates and getattr(self.request, '_normal_enable_stage3_handoff_events', False):
            capability('handoff_reply', '把本轮接话权交给另一位当前有权限的在场角色。若应由对方单独回答，可在调用后输出自然沉默；若当前角色先说一句再交接，可正常回复。', {
                'type':'object','properties':{'reply_character_id':{'type':'string','enum':[r['reply_character_id'] for r in self.candidates]},
                'reason':{'type':'string','minLength':1,'maxLength':300}},
                'required':['reply_character_id','reason'],'additionalProperties':False}, self.handoff)

    async def schedule(self, arguments):
        from .autonomous_schedule import validate_schedule
        if self.lifecycle or getattr(self.request, '_normal_dead_spirit_reply', False):
            raise HarnessToolValidationError('角色已死亡；本轮灵魂回应不能安排后续消息或提醒')
        if not self.settings.enabled:
            raise HarnessToolValidationError('用户已关闭主动消息，不能承诺定时发送')
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
                    'note': '同一提醒已暂存，无需重复操作；回复保存时只创建一份任务'}
        if len(self.schedules)>=4:
            raise HarnessToolValidationError('每轮最多4个调度草案')
        self.schedules.append(plan)
        return {'staged':True,'id':plan['id'],'kind':plan['kind'],'summary':plan['plan'].get('summary',plan['plan'].get('seed')),
                'note':'回复保存成功后任务同时生效'}

    def finalize_delivery(self, data):
        from .autonomous_followup import finalize_followup
        error = self.shortcut.delivery_error(data) if self.shortcut.description else ''
        if error:
            raise ValueError(error)
        dead = bool(self.lifecycle or getattr(self.request, '_normal_dead_spirit_reply', False))
        if dead:
            self.schedules.clear()
        if self.reminder_expected and not dead and not any(p['kind'] == 'agreed' for p in self.schedules):
            raise ValueError('用户明确给出了几秒/分钟/小时后的提醒要求，须先stage_schedule(kind=agreed)，不能只口头承诺')
        decision = finalize_followup(self, data)
        # Execution receipts are independent of style and semantic prose review.
        # Internal scheduler instructions are never a fresh user death event.
        if not getattr(self.request, '_normal_internal_proactive_trigger', False):
            if self.death_expected and self.lifecycle is None:
                raise ValueError('本轮明确终局事件须先调用stage_character_death保存生命周期，再交付回复')
        return decision

    async def death(self, arguments):
        mid = arguments['source_message_id']
        row = next((m for m in user_batch(self.history) if m.get('message_id')==mid), None)
        if row is None or getattr(self.request, '_normal_dead_spirit_reply', False):
            raise HarnessToolValidationError('必须引用本轮真实用户消息，已死亡状态不能重复写入')
        # The model judges actual outcome from original context. A prompt command
        # alone is not evidence; semantic instructions prohibit jokes/hypotheticals.
        if re.search(r'如果|假如|假设|梦到|开玩笑|假死|装死|what if', row.get('content',''), re.I):
            raise HarnessToolValidationError('假设、玩笑或假死不是本轮实际终局死亡')
        if not re.search(r'死|斩首|爆头|心脏|喉咙|death|died|dead|kill|murder', row.get('content',''), re.I):
            raise HarnessToolValidationError('引用原文没有死亡事件，不能改变生命周期')
        self.lifecycle = dict(arguments)
        cancelled = [item['id'] for item in self.schedules]
        self.schedules.clear()
        return {'staged':True,'state':'dead','cancelled_schedule_ids':cancelled,
                'note':'成功保存本轮终局回复时生效；本轮暂存的后续消息和提醒同时取消'}

    async def handoff(self, arguments):
        from .service import _normal_handoff_target_allowed
        from .normal_speaker import effective_speaker_character_id
        if arguments['reply_character_id'] not in {c['reply_character_id'] for c in self.candidates} or not await _normal_handoff_target_allowed(
                self.request, arguments['reply_character_id'], current_reply_id=effective_speaker_character_id(self.request)):
            raise HarnessToolValidationError('该角色不在本轮有权限的接话候选中')
        self.request._normal_handoff_router_result = dict(arguments)
        return {'staged':True,**arguments}
