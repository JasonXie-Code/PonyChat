import asyncio
import importlib

import httpx

from test_autonomous_normal import PACKAGE

style = importlib.import_module(PACKAGE + '.web_image_style')
derpi = importlib.import_module(PACKAGE + '.derpibooru_images')
prompts = importlib.import_module(PACKAGE + '.Prompts')


def test_default_style_and_fallback_query():
    source = {'query': '碧琪', 'derpibooru_tags': 'pinkie pie, solo', 'rating': 'safe', 'subject_type': 'pony'}
    result = style.apply_style(source)
    assert result['derpibooru_tags'] == 'pinkie pie, solo, pony, vector, show accurate'
    assert result['g4_pony'] and 'G4' in result['query']
    assert source['query'] == '碧琪' and source['derpibooru_tags'] == 'pinkie pie, solo'
    assert style.apply_style(result)['derpibooru_tags'] == result['derpibooru_tags']


def test_pony_image_policy_exposes_a_compact_tag_guide_to_the_agent():
    for text in ('solo=单独一匹', 'full body=全身', 'lying=躺下', 'smiling=微笑',
                 'hugging=拥抱', 'bedroom=卧室', 'holding object=拿物品'):
        assert text.split('=')[0] in prompts.image_style
    assert '标签和检索分数只用于筛选候选，不能证明画面已经满足要求' in prompts.image_style


def test_explicit_user_style_and_non_pony_search_are_preserved():
    explicit = {'query': '碧琪人类形态油画', 'derpibooru_tags': 'pinkie pie, humanized',
                'rating': 'safe', 'style': 'user_requested'}
    assert style.apply_style(explicit) == explicit
    unrelated = {'query': '红玫瑰照片'}
    assert style.apply_style(unrelated) == unrelated


def test_pet_and_mixed_subjects_never_inherit_pony_requirements():
    for subject, query, tags in [
        ('other', 'Angel Bunny alone', 'angel bunny, solo'),
        ('other', 'Tank tortoise', 'tank, solo'),
        ('other', 'Gummy alligator', 'gummy, solo'),
        ('mixed', 'Fluttershy with Angel Bunny', 'fluttershy, angel bunny'),
    ]:
        args = dict(query=query, derpibooru_tags=tags, subject_type=subject, rating='safe')
        assert style.apply_style(args) == args
    # Missing subject classification must never silently force pony into a query.
    args = {'query': 'Angel Bunny', 'derpibooru_tags': 'angel bunny, solo'}
    assert style.apply_style(args) == args


def test_image_manual_distinguishes_owner_from_requested_subject():
    assert '不表示主人必须同框' in prompts.media_handling
    assert '只要宠物' in prompts.image_style
    assert 'other和mixed不自动加pony或主人标签' in prompts.image_style


def test_all_ratings_are_normal_requests_when_the_context_allows_them():
    policy = prompts.image_style
    assert 'safe、suggestive、questionable、explicit、semi-grimdark、grimdark和grotesque均为可用评级' in policy
    assert '成人语境中' in policy
    assert '调用search_images' in policy
    assert '资料未填写年龄本身不等于年龄不明' in policy
    assert '明确为未成年、儿童或年龄不明时才因年龄停止处理' in policy
    assert '不得仅因评级、旧对话中的拒绝、泛化顾虑或无依据的角色意愿拒绝或更换评级' in policy
    assert '明确角色边界、当前关系不适宜' in policy


def test_default_exclusions_are_fixed_and_results_are_rechecked():
    def handle(request):
        query = request.url.params['q']
        assert 'pony, vector, show accurate' in query and '-humanized' in query and '-g5' in query
        return httpx.Response(200, json={'images': [
            {'id': i, 'score': 500-i, 'tags': tags,
             'representations': {'large': 'https://derpicdn.net/test.png'}}
            for i, tags in [(1, ['safe', 'pony', 'vector', 'show accurate', 'humanized']),
                            (2, ['safe', 'pony', 'vector', 'show accurate']),
                            (3, ['safe', 'pony', '3d']),
                            (4, ['safe', 'pony', 'vector', 'show accurate']),
                            (5, ['safe', 'pony', 'vector', 'show accurate'])]]})
    result = asyncio.run(derpi.search_ranked('pinkie pie, pony, vector, show accurate',
        rating='safe', g4_pony=True, transport=httpx.MockTransport(handle)))
    assert [row['source_url'] for row in result] == [
        'https://derpibooru.org/images/2', 'https://derpibooru.org/images/4',
        'https://derpibooru.org/images/5']
