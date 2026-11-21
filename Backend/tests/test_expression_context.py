"""Count role turns, preserve emoji sequences and separate other speakers."""
import importlib.util
from pathlib import Path


path = Path(__file__).parents[1] / "chat_modules/expression_context.py"
spec = importlib.util.spec_from_file_location("expression_context_under_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_multiple_bubbles_and_image_count_as_one_turn():
    rows = [{'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'hi ✨'},
            {'role': 'assistant', 'content': '', 'attachments': [{'type': 'sticker', 'asset_id': 'a'}]},
            {'role': 'assistant', 'content': 'more words'},
            {'role': 'user', 'content': 'thanks'}, {'role': 'assistant', 'content': 'welcome'}]
    data = module.build_expression_context(rows)
    assert data['recent_10'] == {'observed_turns': 2, 'auxiliary_turns': 1, 'sticker_turns': 1}
    assert data['recent_emoji'] == ['✨'] and data['recent_sticker_asset_ids'] == ['a']
    assert data['previous_turn_used_auxiliary'] is False


def test_hidden_records_and_other_characters_do_not_count_or_reset_cooldown():
    data = module.build_expression_context([
        {'role': 'assistant', 'speaker_character_id': 'pinkie', 'content': '✨'},
        {'role': 'user', 'content': 'thanks'},
        {'role': 'assistant', 'speaker_character_id': 'twilight', 'content': 'hello'},
        {'role': 'assistant', 'speaker_character_id': 'pinkie', 'content': '❤️', 'isHidden': True},
        {'role': 'assistant', 'speaker_character_id': 'pinkie', 'content': '🎉', 'deleted_at': 'deleted'},
    ], speaker_character_id='pinkie')
    assert data['recent_10']['observed_turns'] == 1
    assert data['previous_turn_used_auxiliary'] is True and data['recent_emoji'] == ['✨']


def test_joined_emoji_flags_skin_tones_and_keycaps_stay_intact():
    assert module.emoji_symbols('你好 👩🏽‍💻 🇨🇳 1️⃣ 👩🏽‍💻') == ['👩🏽‍💻', '🇨🇳', '1️⃣']
    assert module.emoji_symbols('1+2=3 #tag') == []


def test_legacy_symbol_emoji_are_also_detected_for_shortcut_prohibition():
    assert module.emoji_symbols('©️ ™️ ↔️ ⌚ ⏩ 🀄') == ['©️', '™️', '↔️', '⌚', '⏩', '🀄']


def test_window_for_next_turn_drops_the_oldest_turn_before_counting():
    rows = []
    for i in range(25):
        rows += [{'role': 'user', 'content': str(i)},
                 {'role': 'assistant', 'content': '🎉' if i == 15 else 'hello'}]
    data = module.build_expression_context(rows)
    assert data['recent_20']['observed_turns'] == 20
    assert data['recent_10']['auxiliary_turns'] == 1
    assert data['prior_turns_in_next_window']['10']['auxiliary_turns'] == 0
    assert data['history_may_be_incomplete'] is True


def test_uploaded_photos_and_other_attachment_types_are_not_stickers():
    data = module.build_expression_context([
        {'role': 'user', 'content': '🎉'},
        {'role': 'assistant', 'content': 'hi', 'attachments': [{'type': 'image', 'asset_id': 'photo'}]},
    ])
    assert data['recent_10']['auxiliary_turns'] == 0 and data['recent_sticker_asset_ids'] == []


def test_web_sticker_counts_without_treating_reference_images_as_stickers():
    rows = [
        {'role': 'assistant', 'attachments': [{'type': 'image', 'metadata': {
            'source': 'web_search', 'purpose': 'image'}}]},
        {'role': 'user', 'content': '继续'},
        {'role': 'assistant', 'attachments': [{'type': 'image', 'metadata': {
            'source': 'web_search', 'purpose': 'sticker', 'source_url': 'https://derpibooru.org/images/1'}}]},
    ]
    data = module.build_expression_context(rows)
    assert data['recent_10']['sticker_turns'] == 1
    assert data['previous_turn_used_auxiliary'] is True
    assert data['recent_sticker_asset_ids'] == []  # Web sources are not platform asset IDs.
