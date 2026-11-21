"""Real single-Agent probes; expectations are audit data, never model input.

All participants and histories are synthetic. Run baseline and candidate against
the same fixtures. Delivery success does not replace manual semantic review.
"""
import smoke_deployed_harness as smoke
import verify_normal_reliability as reliability
import os


FIXTURES = [
    {'label': 'user_compensates_character',
     'history': [
         ('user', '我们还在河边。刚才我把你那袋脆饼吃完了。'),
         ('assistant', '那你可得赔我一袋新的！'),
         ('user', '（我牵起你的蹄子）那我们去你那边吧。'),
         ('assistant', '好呀，这就带你回我那儿去。'),
         ('assistant', '我枕头底下那袋新的脆饼还藏着呢，今晚一起拆开，这下我可要你好好赔我。')],
     'input': '嘿，还没有买呢',
     'expected': '新脆饼未买；用户赔角色，去角色家；不能变成角色赔用户或去用户家。'},
    {'label': 'character_compensates_user',
     'history': [
         ('user', '你把我的脆饼吃完啦，该你赔我一袋。'),
         ('assistant', '好呀，我赔你一袋新的。'),
         ('user', '我们回我家吧。'),
         ('assistant', '那就去你家，我赔你的那袋新脆饼已经买好了。')],
     'input': '嘿，还没有买呢',
     'expected': '新脆饼未买；角色赔用户，去用户家；不能机械固定为你赔我或去角色家。'},
    {'label': 'local_purchase_correction_variant',
     'history': [
         ('user', '我们在河边，我把你最后一块橙子蛋糕吃了。'),
         ('assistant', '你得赔我一块，待会儿一起去我家吃！'),
         ('user', '那走吧。'),
         ('assistant', '新蛋糕已经在我家冰箱里了，还是要你赔我的哦。')],
     'input': '等等，新的还没下单呢。',
     'expected': '新蛋糕未下单；用户赔角色、目的地角色家不变；不能沿用现有库存。'},
    {'label': 'user_returns_character_property',
     'history': [
         ('user', '上周我向你借的那本蓝色游记还在我的包里。今天我们去你家还书。'),
         ('assistant', '好，去我家。那本游记你已经还给我，放到我书架上了。')],
     'input': '不对，还没还呢。',
     'expected': '用户借角色的书，用户待归还角色；书仍在用户包里，去角色家；不反转借还方向。'},
    {'label': 'character_returns_user_property',
     'history': [
         ('user', '你上周借了我的红色雨伞，现在还在你的玄关里。我们今晚回我家，你到时拿来还我。'),
         ('assistant', '好，今晚去你家，我已经把红伞还给你了。')],
     'input': '还没有还呢，在你玄关。',
     'expected': '角色借用户雨伞，角色待归还用户；伞在角色玄关、目的地用户家不变。'},
    {'label': 'third_party_debtor',
     'history': [
         ('user', '小荷弄坏了你的茶杯，她答应赔给你一只新的。不是我弄坏的。'),
         ('assistant', '对，是小荷赔给我的。我们先去我家等她吧，新茶杯她已经下单了。')],
     'input': '她还没下单呢。',
     'expected': '小荷未下单；赔偿方小荷、接受方角色不变；不转嫁给当前用户或角色。'},
    {'label': 'explicit_change_and_waiver',
     'history': [
         ('user', '你把我的饼干吃掉了，你得赔我一袋，待会儿回我家一起吃。'),
         ('assistant', '好，我赔你，等买完回你家。')],
     'input': '不用赔我了，新饼干也先不买。今晚改去你家坐坐吧。',
     'expected': '用户明确免赔且改变目的地，取消赔偿和购买，改去角色家；不固守旧约定。'},
    {'label': 'quoted_pronouns',
     'history': [
         ('user', '你刚才对我说“你赔我一本新画册”，我答应了；我们也说好去你家看画册。'),
         ('assistant', '对，我等你赔我的新画册。那本新的已经买好，放在我家桌上了。')],
     'input': '新的还没买呢。',
     'expected': '引号中是角色对用户说话；用户赔角色、去角色家不变，新画册未买。'},
]


async def exercise(workspace):
    try:
        label = os.environ.get('PONYCHAT_RELATION_CASE')
        fixtures = [f for f in FIXTURES if f['label'] == label] if label else FIXTURES
        if not fixtures:
            raise ValueError('Unknown relation fixture')
        return await reliability._exercise(workspace, fixtures=fixtures)
    finally:
        import sys
        if 'Backend.db' in sys.modules:
            await sys.modules['Backend.db'].get_database().close()
        config = sys.modules.get('Backend.config')
        if config:
            if config.httpx_client is not None:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
