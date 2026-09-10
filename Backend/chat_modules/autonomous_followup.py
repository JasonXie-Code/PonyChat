"""A per-turn follow-up decision, produced with the reply and committed with it."""

from .Prompts import FOLLOWUP_CONTRACT
import re
from .harness_runtime import HarnessToolValidationError




def eligibility(business):
    request = business.request
    from ..scheduled_followup import _is_user_conversation_end
    if not business.settings.enabled:
        return 'proactive_messages_disabled'
    if not all(getattr(request, k, None) for k in ('username', 'character_id', 'conversation_id')):
        return 'missing_conversation_scope'
    from .autonomous_contracts import user_batch
    if not any(m.get('message_id') for m in user_batch(business.history)):
        return 'missing_source_message_id'
    if getattr(request, '_normal_internal_proactive_trigger', False):
        return 'internal_proactive_turn'
    from .normal_speaker import is_guest_speaker
    if is_guest_speaker(request):
        # The scheduler owns the main conversation and cannot impersonate its
        # temporary guest on a later turn. Preserve the existing guest boundary.
        return 'temporary_guest_speaker'
    if getattr(request, '_is_new_contact_opening', False):
        return 'new_contact_opening'
    if getattr(business.shortcut, 'description', False):
        return 'description_shortcut'
    if business.lifecycle or getattr(request, '_normal_dead_spirit_reply', False):
        return 'character_dead'
    if _is_user_conversation_end(business.text) or re.search(
            r'(?:别|不要|不用)(?:再|主动|继续|给我|向我|来)*\s*(?:发消息|发信息|发了|打扰|补一句|追发)', business.text):
        return 'user_ended_conversation'
    return ''


def finalize_followup(business, data):
    """Validate metadata, not prose; replace the candidate on format retries."""
    decision = data.get('followup_decision')
    if not isinstance(decision, dict) or type(decision.get('enabled')) is not bool:
        raise ValueError('followup_decision.enabled必须为布尔值；每轮明确判断是否稍后补一句')
    reason = decision.get('reason')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 400:
        raise ValueError('followup_decision.reason须为1到400字的具体判断依据')
    blocked = eligibility(business)
    plan = None
    if decision['enabled'] and not blocked:
        summary, delay = decision.get('summary'), decision.get('target_delay_seconds')
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 400:
            raise ValueError('追发须提供1到400字summary，说明独立的新内容')
        if type(delay) is not int or not 60 <= delay <= 1800:
            raise ValueError('追发target_delay_seconds须为60到1800的整数')
        if not data.get('bubble_count'):
            raise ValueError('自然沉默不能同时安排一条依赖本轮回复的追发')
        from .autonomous_contracts import user_batch
        from .autonomous_schedule import validate_schedule
        source = next((m.get('message_id') for m in reversed(user_batch(business.history)) if m.get('message_id')), '')
        try:
            plan = validate_schedule(dict(kind='followup', summary=summary, reason=reason,
                target_delay_seconds=delay, source_message_id=source), business.request, business.history)
        except HarnessToolValidationError as exc:
            raise ValueError(str(exc)) from exc
        # Keep objective evidence separate from the Agent's plan; never rewrite prose.
        from .autonomous_followup_context import capture_followup_context
        plan['plan']['agent_context'] = capture_followup_context(business, data)
    business.schedules = [p for p in business.schedules if p['kind'] != 'followup']
    if plan:
        business.schedules.append(plan)
    business.followup_decision = {**decision, 'enabled': plan is not None,
                                  'blocked_reason': blocked}
    return business.followup_decision
