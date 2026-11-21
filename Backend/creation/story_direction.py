"""Ephemeral creative direction, reproducible for retries of one request."""
import hashlib

DIRECTIONS = (
    '顺着当前线索推进，让角色主动做出一个符合性格的小行动。',
    '让一个之前提到的细节产生新的后果，自然推动情节。',
    '适度推进时间或场景，让关系或局势有一点新的发展。',
    '加入一个有铺垫的小意外或新发现，让剧情自然转折。',
    '让角色对眼前的事情发现另一种解释，带出新的选择。',
    '通过符合情境的打断或误会，让发展暂时偏离原来的方向。',
    '让眼前的计划暂时受阻，角色退一步重新考虑，但不要抹去已有事实。',
    '适当回顾前面留下的线索，让角色重新面对尚未解决的问题。',
    '放缓节奏，用细节、动作或交流让情绪发生微妙变化。',
)


def direction_index(request_id):
    return int.from_bytes(hashlib.sha256(request_id.encode()).digest()[:8], 'big') % len(DIRECTIONS)


def generation_hint(request):
    continuing = getattr(request, 'continue_story', False)
    if not continuing and not request.regenerate:
        return None
    index = direction_index(request.request_id)
    action = ('请接着最后一条角色回复继续写，保留已有内容和事实，不复述上一段，也不要替用户决定或编造用户的回应。'
              if continuing else '请重新回答当前这一步，尝试不同的切入点、动作或细节，避免照抄上一版本。')
    return {'role': 'user', 'content': action + '\n本次可选创作方向：' + DIRECTIONS[index] +
            '\n方向仅作灵感，优先遵守用户的明确要求、角色设定和已有情节。'
            '非故事内容采用适合当前话题的表达变化，不要强加剧情。直接输出角色正文，不解释这些提示。'}
