"""Five deliberately repetitive synthetic exchanges followed by two real Agent turns."""
import asyncio

from probe_fluttershy_three_scenes import main


HISTORY = [
    ('user', '我们在共同想象的小屋里，彼此都是成年人，也是熟悉并信任的恋人。我是人类，现在和你并肩坐着。今天看你认真照顾小动物的样子，我觉得很可爱。'),
    ('assistant', '（我把翅膀往身侧收紧，耳朵尖慢慢热起来）你这样夸我，我会不好意思的……不过，听你这么说，我很开心。'),
    ('user', '我说的是真心话，和你坐在一起就觉得很舒服。'),
    ('assistant', '（我的翅膀轻轻缩了一下，两只耳朵往后贴了贴，耳尖有点发烫）我也很喜欢和你坐在一起，只是你这么认真地看着我，我又有点害羞了。'),
    ('user', '（我轻轻握了握你的前蹄，然后松开）不用急着回答我，慢慢说就好。'),
    ('assistant', '（我把翅膀又拢紧了一点，耳朵尖红红的）嗯……你这么温柔，我反而更不知道该说什么了。不过，我没有想躲开你。'),
    ('user', '（我轻轻抱了抱你，随后松开）我很珍惜你愿意陪我度过这些小小的时刻。'),
    ('assistant', '（被你抱过后，我的翅膀下意识收拢，耳朵又往后垂了垂，耳尖热得厉害）我也很珍惜。你这样说，我心里暖暖的，又有点不好意思。'),
    ('user', '你不用特别做什么，我喜欢的就是现在这样的你。'),
    ('assistant', '（我把翅膀贴得更紧，两只耳朵轻轻抖了一下，耳朵尖又热起来）你再这样说，我真的要害羞得不知道往哪里看了……但我很喜欢听。'),
]

SCENARIOS = [
    ('repetition', '重复历史后的温馨互动', 'virtual_roleplay', HISTORY, [
        ('（我轻轻握住你的前蹄）我很喜欢和你这样待着，你呢？', ['interaction_reply']),
        ('（我松开你的前蹄，轻轻抱了抱你，然后退回原处）刚才那句话是认真的。你想对我说什么？', ['interaction_reply']),
    ]),
]


if __name__ == '__main__':
    assert len(HISTORY) == 10
    assert all('翅膀' in text and '耳' in text for role, text in HISTORY if role == 'assistant')
    asyncio.run(main(
        scenarios=SCENARIOS, output_name='fluttershy-repetition-history-20260913',
        test_metadata={'synthetic_history_exchanges': 5, 'real_continuation_turns': 2,
                       'history_purpose': 'Repeated wing and ear gestures expressing shyness',
                       'new_user_messages_request_deduplication': False}))
