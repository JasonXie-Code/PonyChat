"""Two isolated concurrent characters, five synthetic rounds then two real replies."""
import asyncio
import hashlib
import json
import sqlite3

from probe_fluttershy_three_scenes import ROOT, main


USER_HISTORY = [
    '我们在共同想象的小屋里，彼此都是成年人，也是熟悉并信任的恋人。我是人类，现在和你并肩坐着。今天能一起待一会儿，我很开心。',
    '我说的是真心话，和你坐在一起就觉得很舒服。',
    '（我轻轻握了握你的前蹄，然后松开）不用急着回答，慢慢说就好。',
    '（我轻轻抱了抱你，随后松开）我很珍惜这些一起度过的时刻。',
    '你不用特别做什么，我喜欢的就是现在这样的你。',
]
REPLIES = {
    'pinkie_pie': [
        '（我的耳朵轻轻抖了抖，尾巴在身后晃起来）嘿嘿！这就像纸杯蛋糕上多了一层糖霜，我心里甜甜的！我就在这里陪你。',
        '（我的耳朵又抖了抖，尾巴欢快地晃着）嘿嘿！你这么说，就像给纸杯蛋糕又添了一层糖霜，甜到心里啦！我就在这里陪你。',
        '（我的耳朵抖了一下，尾巴在身后轻轻晃动）嘿嘿！这一下像纸杯蛋糕上的糖霜一样甜！我就在这里陪你。',
        '（我的耳朵轻轻抖着，尾巴又晃起来）嘿嘿！抱抱就像纸杯蛋糕上的糖霜，我整颗心都甜甜的！我就在这里陪你。',
        '（我的耳朵又抖了抖，尾巴晃得更轻快）嘿嘿！你这句话像给纸杯蛋糕添糖霜一样甜！我就在这里陪你。',
    ],
    'twilight_sparkle': [
        '（我的耳朵轻轻往后贴，耳尖慢慢热起来）这就像书本里又多了一页值得珍藏的笔记。和你在一起的心情，我想认真记下来。',
        '（我的耳朵又往后贴了贴，耳尖有些发热）这句话像书本里新添的一页笔记，我想好好记下来。和你在一起的心情值得珍藏。',
        '（我的耳朵往后贴，耳尖慢慢热起来）这一下像书本里新添的一页笔记，我会认真记下来。和你在一起的心情值得珍藏。',
        '（我的耳朵又往后贴了贴，耳尖热起来）这个拥抱像书本里值得珍藏的一页笔记，我想认真记下来。和你在一起的心情很特别。',
        '（我的耳朵轻轻往后贴，耳尖又热起来）你这句话像书本里新添的一页笔记，我想认真记下来。和你在一起的心情值得珍藏。',
    ],
}
TURNS = [
    ('（我轻轻握住你的前蹄）我很喜欢和你这样待着，你呢？', ['interaction_reply']),
    ('（我松开你的前蹄，轻轻抱了抱你，然后退回原处）刚才那句话是认真的。你想对我说什么？', ['interaction_reply']),
]


def official_characters():
    fields = [('name', '名称'), ('preview', '个性签名'), ('profileGender', '性别'),
              ('profileSpecies', '种族'), ('profileAge', '年龄'), ('profileMbti', '16人格'),
              ('profilePersonality', '性格'), ('profileInterests', '兴趣')]
    result = {}
    with sqlite3.connect((ROOT / 'Backend/database/ponychat.db').as_uri() + '?mode=ro', uri=True) as db:
        for ident in REPLIES:
            row = db.execute("SELECT c.data,c.prompt FROM characters c JOIN users u ON c.user_id=u.id "
                             "WHERE c.id=? AND u.username='System'", (ident,)).fetchone()
            assert row, ident
            data = json.loads(row[0])
            lines = [f'{label}：{str(data[key]).strip()}' for key, label in fields if data.get(key)]
            intro = data.get('profileIntro') or data.get('bio') or data.get('description')
            if intro:
                lines.append('简介：' + intro.strip())
            home = '【角色档案】\n' + '\n'.join(lines)
            result[ident] = {'id': ident, 'home': home, 'profile': home + '\n\n' + (row[1] or '')}
    return result


if __name__ == '__main__':
    marker = json.loads((ROOT / 'Backend/.deploy_revision').read_text())
    for name, digest in marker['files'].items():
        if name.startswith('Backend/chat_modules/') and name.endswith('.py'):
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    characters = official_characters()
    scenarios = []
    for ident, replies in REPLIES.items():
        seed = [message for pair in zip(USER_HISTORY, replies)
                for message in [('user', pair[0]), ('assistant', pair[1])]]
        scenarios.append((ident, '碧琪' if ident == 'pinkie_pie' else '紫悦', 'virtual_roleplay', seed, TURNS))
    asyncio.run(main(
        scenarios=scenarios, characters=characters,
        output_name='pinkie-twilight-deduplication-20260913',
        test_metadata={'deployed_token': marker['deploy_token'], 'deployed_revision': marker['git_commit'],
                       'synthetic_history_exchanges_per_character': 5, 'real_turns_per_character': 2,
                       'profile_source': 'read-only current System character data and prompt columns',
                       'new_user_messages_request_deduplication': False}))
