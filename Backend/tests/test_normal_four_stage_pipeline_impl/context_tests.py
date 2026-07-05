

def test_step2_fact_judgement_prompt_keeps_normal_turns_informative():
    assert "每轮都要根据证据整理 Step 3 主回复可直接使用的事实" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前用户消息里明确写出的动作" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要因为没有冲突就留空" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "普通回合通常也应是 ok，而不是 none" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "每轮都尽量输出 available_facts、subject_boundaries、writing_guidance" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "scene_anchor/scene_card" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "作为内部核对锚点" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要要求最终正文逐字复述微观位置" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "description_request" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "dialogue_allowed" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "动作-心理-低信息短音模板" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "current_user_action" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "terminal_event" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "relationship_evidence" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "action_feasibility" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "偏好、角色职业、旧记忆、过去承诺" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "昨天/今早刚做过" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "新烤/新做" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "writing_guidance 不得再建议 Step 3" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要用不忙不忙否定用户的忙" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "自然语言地点/位置句由你负责事实化" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "我们现在是在一楼客厅的沙发上" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "稳定角色设定里的住处、床单、墙纸、房间装饰不是当前可见事实" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "近期用户说在一楼客厅却候选写成三楼房间" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "关键物品 holder/location/state" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "Step 1 的 expression_policy/proactive_seed 是计划文本，不是事实证据" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能写进 available_facts、scene_anchor.items、scene_card 或 writing_guidance" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前动作方式优先于旧偏好/旧记忆" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前现场问句与旧记忆抽查要分开" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前正在吃/拿/做的东西写成答案" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能把“当前正在沾/拿/递/看/站着”等改写成旧的" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "证据来源不得冒名" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "移动/回家/去某处/带路/邀请的提议主体必须保持" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "角色开口让用户来、角色把用户带回来、用户跟着角色回来" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "死亡/不可参与边界" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "问东问西或作为正在屋内睡觉的家人" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "跨会话/上一场物品不继承为当前现场" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能因为它最近出现过、属于同一用户同一角色或命中描述关键词" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能写成当前可见、正在晃动、正在持有或此刻发生" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "否定式重新提到" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "history_facts、forbidden_uses、stale/background" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能升级到 available_facts、scene_anchor.items、scene_card" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前用户消息若用“当前事实/现在/只是/只有”等限定现场" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "对话代词视角硬规则" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "描写/心理/身体感受主体必须保持" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "无论用户性别、角色性别或当前体位如何" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "用户反馈/角色听到的评价" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能改写成当前角色正在感受用户身体内部状态" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "若最近真实对话、上下文记忆、Step 1 计划或旧摘要写成" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "这家伙里面好紧" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "已确认立场/结果不得被角色性格反转" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "挑战开始或首次失败但当前角色尚未明确服输时" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "我认输/你赢了/我服了/算你厉害" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不认输/不服输/不服气/还没输/不算输" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "available_facts 必须写出该立场" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "subject_boundaries 或 forbidden_inferences 必须显式写明不得反向改写" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "scene_card、writing_guidance 和 subject_boundaries 也不得再写" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不服输的调皮/不服气的笑/嘴上不认输/不能认输" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "还能再来/下次赢回来/你等着/这不算输/嘴硬" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "有遗憾/有点难过/不甘心但承认结果" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不得写“保持不服输但已认输”这种混合口径" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "“不要重复上一句原话”不是改立场许可" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "禁止为了避免复读而写成“不服气/不服输/嘴硬/下次肯定赢回来/你等着/这不算输”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "禁止把不重复原话改成反向嘴硬" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "角色设定里的好胜、不服输、害羞或傲娇" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "保留已确认立场，只写该立场后的身体/心理/动作余韵" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "二人动作施受关系必须保持" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "用户写“你拉着我/你把我/你带我/你让我”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "“你帮我…”动作主体固定" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前角色帮当前用户脱掉裤子" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能把这条历史动作改成“当前用户主动脱裤子”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "Step 1 的 expression_policy/proactive_seed 或 Memory Recall 的 writing_guidance" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "assistant 里的承诺/要求归属必须保持" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前角色承诺让用户舒服" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "承诺方向固定例" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不得写“当前角色的承诺让用户舒服”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "用户未来条件句边界" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不得逐字写入用户旧条件句原文" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不得把未来目标写成已经发生的高潮/顶峰/释放/余韵/事后事实" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "胸口/胸前只有胸膛或绒毛" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "涂到胯间后腿之间就是涂到小马乳房所在位置" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "身体术语体态边界" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "用户要求“应该怎么改/只给正确写法”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不得把自己的身体末端写成指尖、手指" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不需要强制逐字保留原句其他动作或状态" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "用户私人空间储物边界" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能断言储物内容、库存或可取物" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "用户家储物内容未知，不能断言冰箱/柜子里有什么" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "unsupported_current_items 必须列出本轮高风险误写项" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "把用户家家具说成我的柜子/我这边柜子" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不得用“我的柜子/我这边柜子/我房间里/我厨房里”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "身体状态连续性必须结构化" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "刚起床/清晨场景特殊边界" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不能自动补刷牙、牙膏、薄荷味" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "旧场景饮品/道具边界" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "上一场酒吧、餐厅、厨房或派对里的啤酒" in _STEP2_FACT_JUDGEMENT_SYSTEM


def test_self_cognition_prompt_keeps_stable_room_setting_out_of_current_scene():
    assert "setting_anchors 也不是当前可见场景事实" in _SELF_COGNITION_SYSTEM
    assert "必须服从 Step 1/Step 2 的 scene_anchor" in _SELF_COGNITION_SYSTEM
    assert "除非 scene_anchor 明确当前就在该稳定房间" in _SELF_COGNITION_SYSTEM
    assert "第一次来用户家/用户房间" in _SELF_COGNITION_SYSTEM
    assert "不要把角色自己的住处、卧室、床、海报、奖杯、宠物" in _SELF_COGNITION_SYSTEM
    assert "亲属/朋友/同伴名单也不是当前可参与名单" in _SELF_COGNITION_SYSTEM
    assert "不要把此人写成当前会醒来、看到、开门、问话、责怪" in _SELF_COGNITION_SYSTEM
    assert "避免回到角色默认住处、卧室、床单、墙纸或旧房间布置" in _SELF_COGNITION_SYSTEM


def test_material_and_fact_prompts_keep_user_home_pronouns():
    assert "user 消息里" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "我家/我的房间" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "用户家/用户房间" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "绝不能把“我的房间”解析成当前角色的房间" in _NORMAL_MATERIAL_PREP_SYSTEM

    assert "user 消息第一人称地点归属硬规则" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前地点整理为用户家/用户房间" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "角色稳定住处、卧室、海报、床、奖杯、宠物" in _STEP2_FACT_JUDGEMENT_SYSTEM


def test_new_contact_opening_preserves_substantive_first_task():
    assert normal_service._new_contact_opening_should_preserve_user_task(
        "你的乳房在哪个位置？"
    )
    assert normal_service._new_contact_opening_should_preserve_user_task(
        "（我们刚认识不久，这是你第一次来我家。我们洗完澡后来到了我的房间）请详细写出当前你看到的画面。"
    )
    assert not normal_service._new_contact_opening_should_preserve_user_task("你好")


def test_self_cognition_prompt_preserves_confirmed_stance_polarity():
    assert "已确认立场硬优先" in _SELF_COGNITION_SYSTEM
    assert "后续身体状态、心理活动、继续描写、推进剧情、不要复读原句都只是写法请求" in _SELF_COGNITION_SYSTEM
    assert "禁止在 likely_actions、unlikely_actions 或 focus 中出现" in _SELF_COGNITION_SYSTEM
    assert "挑战/服输阶段必须分清" in _SELF_COGNITION_SYSTEM
    assert "likely_actions 和 unlikely_actions 必须保留这个立场" in _SELF_COGNITION_SYSTEM
    assert "挑战开始或第一次失败但当前角色尚未明确服输时" in _SELF_COGNITION_SYSTEM
    assert "不认输/不服输/不服气/还没输/不算输" in _SELF_COGNITION_SYSTEM
    assert "已服输后的好胜只能写成" in _SELF_COGNITION_SYSTEM
    assert "有遗憾/有点难过/不甘心但承认结果" in _SELF_COGNITION_SYSTEM
    assert "不服输的调皮/不服气的笑/嘴上不认输/不能认输" in _SELF_COGNITION_SYSTEM
    assert "还能再来/下次赢回来/你等着/这不算输/嘴硬" in _SELF_COGNITION_SYSTEM
    assert "也不要写“保持不服输但已认输”这种混合口径" in _SELF_COGNITION_SYSTEM


def test_step2_fact_judgement_formats_ok_current_action_into_stage3_material():
    report = {
        "status": "ok",
        "available_facts": ["用户把一只手环到当前角色背后，并轻轻拍当前角色的背。"],
        "subject_boundaries": ["拍背动作由用户发起，不能写成角色主动拍用户。"],
        "writing_guidance": "Step 3 先承接用户拍背造成的即时反应。",
    }

    text = format_fact_judgement_for_stage3(report)

    assert "状态：ok" in text
    assert "用户把一只手环到当前角色背后" in text
    assert "拍背动作由用户发起" in text
    assert "Step 3 先承接用户拍背" in text


def test_step2_fact_judgement_formats_body_feedback_subject_boundary_into_stage3_material():
    report = {
        "status": "needs_boundary",
        "available_facts": ["用户说“好紧”，这是用户对当前接触状态的身体反馈。"],
        "subject_boundaries": [
            "用户说“好紧”是用户反馈，不是当前角色正在感受用户身体内部状态。",
            "当前描写 target 是当前角色的心理活动；当前角色只能写自己的身体状态和听到反馈后的心理。",
        ],
        "forbidden_inferences": [
            "禁止写成这家伙里面好紧、用户身体又热又湿或当前角色差点没把持住。",
        ],
        "writing_guidance": "Step 3 写当前角色听到用户反馈后的心理 + 当前角色自己的身体状态；不要倒写成用户身体内部给当前角色的第一人称感受。",
    }

    text = format_fact_judgement_for_stage3(report)

    assert "用户说“好紧”，这是用户对当前接触状态的身体反馈。" in text
    assert "不是当前角色正在感受用户身体内部状态" in text
    assert "当前描写 target 是当前角色的心理活动" in text
    assert "这家伙里面好紧" in text
    assert "当前角色听到用户反馈后的心理 + 当前角色自己的身体状态" in text


def test_step2_fact_judgement_formats_concession_polarity_boundary_into_stage3_material():
    report = {
        "status": "needs_boundary",
        "available_facts": [
            "当前角色上一句已经说“哈……算你厉害，这次我认输”。",
        ],
        "subject_boundaries": [
            "当前用户要求写当前角色身体状态；必须保持当前角色已认输这一立场。",
            "角色好胜只能写成认输后的不甘心、嘴硬或未来想再试，不能否定本轮认输。",
        ],
        "forbidden_inferences": [
            "禁止写当前角色不认输、不服输、还没输、不算输或没承认输了。",
        ],
        "writing_guidance": "Step 3 写当前角色认输后的身体余韵和情绪，不要把性格里的好胜改成反向事实。",
    }

    text = format_fact_judgement_for_stage3(report)

    assert "哈……算你厉害，这次我认输" in text
    assert "必须保持当前角色已认输这一立场" in text
    assert "角色好胜只能写成认输后的不甘心" in text
    assert "禁止写当前角色不认输、不服输" in text
    assert "不要把性格里的好胜改成反向事实" in text


def test_step2_action_feasibility_reaches_stage3_and_memory_notes():
    report = {
        "status": "needs_boundary",
        "available_facts": [
            "用户说自己这几天有点忙并向当前角色道歉。",
            "用户邀请当前角色今天下午忙完后来用户家喝茶。",
            "当前角色刚送完信，人在老橡树附近路边。",
        ],
        "subject_boundaries": [
            "这几天有点忙的主体是用户，不是当前角色；不要用不忙不忙否定用户的忙。",
            "若回应角色日程，应写角色送完信后可以过去，而不是把用户的忙说成角色不忙。",
        ],
        "forbidden_inferences": [
            "没有证据证明当前角色此刻带着刚烤好的蓝莓松饼。",
        ],
        "action_feasibility": {
            "status": "needs_adjustment",
            "current_activity": "当前角色刚送完信，在路边准备赴约。",
            "supported_items": [],
            "unsupported_current_items": ["刚烤好的蓝莓松饼", "邮包里还温着的松饼"],
            "constraints": ["送信路上与刚从厨房烤好松饼不是同一当前动作。"],
            "guidance": "把松饼改成稍后回家拿、路上买、下次烤，或本轮直接省略。",
        },
        "writing_guidance": "Step 3 先回应用户辛苦和邀请，再按已证实日程自然答应。",
    }

    text = format_fact_judgement_for_stage3(report)

    assert "行动/物品可行性" in text
    assert "无证据当前持有/刚完成=刚烤好的蓝莓松饼、邮包里还温着的松饼" in text
    assert "送信路上与刚从厨房烤好松饼不是同一当前动作" in text
    assert "把松饼改成稍后回家拿、路上买、下次烤" in text
    assert "行动/物品可行性优先级" in text
    assert "不得写成已经带着、新烤/新做、昨天多做、早上刚做" in text

    planner = {**default_planner_result(), "fact_judgement": report}
    memory_notes = build_planner_memory_notes(planner)
    assert "事实边界" in memory_notes
    assert "不要用不忙不忙否定用户的忙" in memory_notes
    assert "无证据当前持有/刚完成：刚烤好的蓝莓松饼" in memory_notes


def test_step2_private_home_inventory_boundary_reaches_stage3_material():
    report = {
        "status": "needs_boundary",
        "available_facts": [
            "云宝在用户家卧室床上，Jason在用户家客厅沙发边。",
            "上一轮云宝想转移话题缓和尴尬气氛，可以问低压力日常问题。",
        ],
        "subject_boundaries": [
            "当前场景在用户家，不是当前角色自己的住处。",
            "用户家储物内容未知，不能断言冰箱/柜子里有什么，只能询问或建议确认。",
        ],
        "forbidden_inferences": [
            "禁止写成冰箱里有果汁、牛奶、饮料或任何未被用户说出的现成食物。",
            "角色喜欢果汁只说明角色偏好，不能升级成用户家冰箱库存。",
        ],
        "uncertainty_points": ["不知道用户家冰箱、厨房、柜子或抽屉里有什么。"],
        "writing_guidance": "Step 3 可以让角色问用户明天早餐想吃什么，或问要不要看看家里有什么；不要提醒用户冰箱里已有某样东西。",
        "action_feasibility": {
            "status": "needs_adjustment",
            "current_activity": "当前角色躺在用户家卧室床上，不能直接知道用户家冰箱库存。",
            "supported_items": [],
            "unsupported_current_items": ["用户家冰箱里的果汁", "用户家柜子里的毯子", "把用户家柜子说成我的柜子"],
            "constraints": ["私人物品/储物内容需要用户说过、角色看见过或当场确认。"],
            "guidance": "改成询问、建议确认或省略具体库存。",
        },
    }

    text = format_fact_judgement_for_stage3(report)

    assert "用户家储物内容未知" in text
    assert "冰箱里有果汁" in text
    assert "角色喜欢果汁只说明角色偏好" in text
    assert "不知道用户家冰箱、厨房、柜子或抽屉里有什么" in text
    assert "无证据当前持有/刚完成=用户家冰箱里的果汁、用户家柜子里的毯子、把用户家柜子说成我的柜子" in text
    assert "改成询问、建议确认或省略具体库存" in text


def test_material_prep_scene_card_carries_physical_state_and_item_boundaries():
    card = format_normal_scene_anchor_card(
        {
            "status": "active",
            "scene_time": {"value": "清晨刚起床"},
            "location": {"site": "用户家", "room": "卧室", "spot": "床上"},
            "current_character": {
                "name": "紫悦",
                "position": {"room": "卧室", "spot": "床边", "posture": "刚醒来"},
                "evidence": "当前用户消息建立清晨醒来场景",
            },
            "items": [],
            "stale_items": ["上一场酒吧里的啤酒只作历史背景"],
            "forbidden_current_items": ["无刷牙/洗漱证据，禁止写牙膏或薄荷味残留"],
            "physical_state": {
                "current_character": {
                    "sleep_state": "刚醒来",
                    "scope": "current_scene",
                    "evidence": "当前用户消息",
                },
                "user": {},
                "stale_states": ["上一场酒吧里的醉意和酒味不继承到清晨卧室"],
                "reset_policy": "reset_on_scene_change",
                "guidance": "按刚起床场景写，旧酒味和牙膏味都不得补成当前感官。",
            },
        }
    )

    assert "物品边界" in card
    assert "上一场酒吧里的啤酒只作历史背景" in card
    assert "禁止写牙膏或薄荷味残留" in card
    assert "身体状态" in card
    assert "睡眠/清醒=刚醒来" in card
    assert "上一场酒吧里的醉意和酒味不继承到清晨卧室" in card
    assert "reset_on_scene_change" in card


def test_step2_physical_state_boundary_reaches_stage3_material():
    report = {
        "status": "needs_boundary",
        "available_facts": ["当前用户建立清晨醒来场景，房间里只有晨光和刚醒的状态。"],
        "forbidden_inferences": [
            "没有刷牙/洗漱证据，禁止写薄荷牙膏味。",
            "上一场酒吧啤酒只作历史背景，不能写成客厅或卧室当前物品。",
        ],
        "physical_state": {
            "current_character": {
                "sleep_state": "刚醒来",
                "sensory_residue": "",
                "scope": "current_scene",
                "evidence": "当前用户消息",
            },
            "user": {
                "fatigue": "刚起床，状态未完全清醒",
                "scope": "current_scene",
                "evidence": "当前用户消息",
            },
            "stale_states": ["上一场酒吧的醉意、啤酒味、咖啡味都不是当前状态"],
            "reset_policy": "reset_on_scene_change",
            "guidance": "Step 3 只能写刚醒和晨光，不写牙膏、啤酒或咖啡残留。",
        },
        "writing_guidance": "按当前清晨卧室事实写。",
    }

    text = format_fact_judgement_for_stage3(report)

    assert "身体状态边界" in text
    assert "睡眠/清醒=刚醒来" in text
    assert "用户=疲惫=刚起床，状态未完全清醒" in text
    assert "上一场酒吧的醉意、啤酒味、咖啡味都不是当前状态" in text
    assert "旧醉酒、疲惫、伤势、牙膏味、酒味、咖啡味等不得写成当前身体状态" in text
    assert "身体/感官新增边界" in text
    assert "清晨刚醒或换场景不能默认已刷牙、洗漱、喝酒、喝咖啡或继承上一场状态" in text


def test_planner_memory_notes_include_scene_anchor_for_step4_pollution_guard():
    planner = {
        **default_planner_result(),
        "fact_judgement": {
            "status": "ok",
            "scene_card": (
                "【普通对话 Step 1 材料准备｜场景锚点】\n"
                "- 地点层级: 中地点=方糖屋 > 小地点=一楼客厅 > 微观地点=沙发区域\n"
                "- 碧琪.position: 中地点=方糖屋 > 小地点=一楼客厅 > 微观地点=沙发上；姿态=坐着"
            ),
        },
    }

    notes = build_planner_memory_notes(planner)

    assert "场景锚点（防污染）" in notes
    assert "方糖屋" in notes
    assert "一楼客厅" in notes
    assert "若最终回复里的地点/姿势/物品与本锚点冲突" in notes


def test_stage3_suppresses_low_priority_material_conflicting_with_action_feasibility():
    planner = {
        **default_planner_result(),
        "proactive_seed": "角色先答应邀请，再提到带新烤的蓝莓松饼过去。",
        "expression_policy": "角色温柔答应，并说正好想带刚烤好的蓝莓松饼过去。",
        "memory_use_policy": "用户喜欢蓝莓松饼焦边；角色答应过以后有空会烤。",
        "fact_judgement": {
            "status": "needs_boundary",
            "forbidden_inferences": ["不能写成当前角色已经烤好松饼或随身带着松饼。"],
            "subject_boundaries": ["用户说自己这几天忙，当前角色不要否定用户的忙。"],
            "action_feasibility": {
                "status": "needs_adjustment",
                "current_activity": "当前角色正在送信途中。",
                "unsupported_current_items": ["蓝莓松饼（未烤）"],
                "constraints": ["角色正在送信，不能同时已经烤好松饼或带着松饼。"],
                "guidance": "可写等会儿回家看看或下次烤，不能写成已经烤好或随身带着。",
            },
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=planner,
        character_prompt_context="小呆喜欢烘焙蓝莓松饼。\n本轮倾向：主动问要不要带刚烤的松饼或小点心过去。",
        recent_messages=[{"role": "user", "content": "今天下午你忙完了来我家喝茶怎么样"}],
        compact_reply_frame=True,
    )

    assert "行动/物品可行性优先级" in block
    assert "已移除与 Step 2 事实边界/行动可行性冲突的低优先级素材" in block
    assert "下一拍动作：角色先答应邀请，再提到带新烤的蓝莓松饼过去" not in block
    assert "表达调度：角色温柔答应，并说正好想带刚烤好的蓝莓松饼过去" not in block
    assert "Step 2 自我认知倾向：主动问要不要带刚烤的松饼" not in block
    assert "可选倾向：主动问要不要带刚烤的松饼" not in block


def test_stage3_suppresses_low_priority_scene_position_material_when_fact_boundary_disagrees():
    planner = {
        **default_planner_result(),
        "proactive_seed": "角色先确认自己位置在测试房间窗边地毯，再复述暗号。",
        "expression_policy": "先说自己还在测试房间窗边地毯，再说云宝在床边。",
        "fact_judgement": {
            "status": "needs_boundary",
            "misleading_sources": [
                "旧记忆或普通场景候选写苹果嘉儿测试房间，但临时群聊见闻写石青派的房间。",
                "场景候选写苹果嘉儿在窗边地毯，但用户指令说你现在就在门口，别挪位置。",
            ],
            "forbidden_inferences": ["不要回落到旧私聊位置或旧测试房间。"],
            "writing_guidance": "Step 3 直接回答苹果嘉儿在石青派房间门口，云宝在床边。",
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=planner,
        character_prompt_context="角色名称：苹果嘉儿\n本轮倾向：先确认用户问戏内位置，再回答当前位置。",
        scene_anchor_card="【普通对话 Step 1 材料准备｜场景锚点】\n- 当前角色位置: 石青派的房间门口\n- 云宝位置: 床边",
        recent_messages=[
            {
                "role": "user",
                "content": "刚才群聊之后，我来私聊你。你现在的位置在哪里？刚才听见的暗号是什么？云宝又在哪？",
            }
        ],
    )

    assert "当前角色位置: 石青派的房间门口" in block
    assert "测试房间窗边地毯" not in block
    assert "下一拍动作：角色先确认自己位置在测试房间窗边地毯" not in block
    assert "表达调度：先说自己还在测试房间窗边地毯" not in block
    assert "已移除与 Step 2 事实边界/行动可行性冲突的低优先级素材" in block
    assert "proactive_seed/下一拍动作含已被 Step 2 场景事实边界降级的位置或地点建议" in block


def test_stage3_suppresses_low_priority_concession_inversion_material():
    planner = {
        **default_planner_result(),
        "proactive_seed": "云宝喘着气，但还想说下次赢回来。",
        "expression_policy": "保留一点不服气的底色，最后写下次赢回来。",
        "fact_judgement": {
            "status": "ok",
            "available_facts": ["云宝已认输，承认这次是用户赢了。"],
            "forbidden_inferences": ["禁止把认输立场反写成不服输、嘴硬或下次赢回来。"],
            "subject_boundaries": ["身体状态主体是云宝本人。"],
            "writing_guidance": "描写认输后的疲惫和不甘心，但不嘴硬、不找借口，把劲头留到下次再试。",
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=planner,
        character_prompt_context=(
            "云宝是好胜飞马。\n"
            "本轮倾向：保留一点不服气的底色，想下次赢回来。\n"
            "本轮不倾向：不要完全放弃。"
        ),
        recent_messages=[
            {"role": "assistant", "content": "哈……算你厉害，这次我认输。"},
            {"role": "user", "content": "（请详细写出当前你的身体状态）"},
        ],
        compact_reply_frame=True,
    )

    assert "已移除与 Step 2 事实边界/行动可行性冲突的低优先级素材" in block
    assert "proactive_seed/下一拍动作含已被 Step 2 禁止的服输反向材料" in block
    assert "expression_policy/表达调度含已被 Step 2 禁止的服输反向材料" in block
    assert "Step 2 自我认知倾向含已被 Step 2 禁止的服输反向材料" in block
    assert "下一拍动作：云宝喘着气，但还想说下次赢回来" not in block
    assert "表达调度：保留一点不服气的底色" not in block
    assert "可选倾向：保留一点不服气的底色" not in block
    assert "描写认输后的疲惫和不甘心" in block


def test_step2_fact_judgement_model_call_is_structured(monkeypatch):
    captured = {}

    async def fake_call(payload, cfg, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs.get("chat_debug_request")
        return SimpleNamespace(
            text=json.dumps(
                {
                    "fact_judgement": {
                        "status": "uncertain",
                        "available_facts": [
                            {"fact": "当前用户显示名叫 Jason", "source": "系统信息", "subject": "当前用户"}
                        ],
                        "forbidden_inferences": ["不能编造旧称呼"],
                        "subject_boundaries": [],
                        "third_party_claims": [],
                        "uncertainty_points": ["旧识关系没有证据"],
                        "must_ask_user": False,
                        "writing_guidance": "只承认显示名，不编旧事。",
                    }
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_planner.call_llm_payload", fake_call)
    result = asyncio.run(
        run_normal_fact_judgement_review(
            [{"role": "user", "content": "你还记得我叫什么吗？"}],
            {"api_key": "test", "model_name": "test-router"},
            planner_result=default_planner_result(),
            evidence_messages=[
                {"role": "system", "content": "【系统信息：当前用户显示名叫 Jason。】"},
                {
                    "role": "system",
                    "content": "【完整角色设定参考】\n角色名称：紫悦\n性格：认真\n用口语文字回复，像真人在聊天窗口里打字",
                },
                {"role": "user", "content": "你还记得我叫什么吗？"},
            ],
            character_prompt_context=(
                "角色名称：紫悦\n"
                "【角色档案】\n名称：紫悦\n性别：雌性\n种族：独角兽\n"
                "性格：认真\nCHARACTER_SECRET"
            ),
            user_species="人类",
            username="tester",
            character_id="char_a",
        )
    )

    assert result["status"] == "uncertain"
    assert result["available_facts"] == ["当前用户显示名叫 Jason；系统信息；当前用户"]
    assert result["forbidden_inferences"] == ["不能编造旧称呼"]
    assert captured["debug"]["stage"] == "NORMAL_STEP_2_FACT_JUDGEMENT_REQUEST"
    system_prompt = captured["payload"]["messages"][0]["content"]
    assert "普通回合通常也应是 ok，而不是 none" in system_prompt
    assert "当前用户消息里明确写出的动作" in system_prompt
    assert "物种/体态主体仲裁" in system_prompt
    assert "当前角色的马/小马/独角兽/天角兽体态规则只适用于当前角色本人" in system_prompt
    assert "不得把角色的蹄子、尾巴、鬃毛、翅膀、角或魔法拿取能力写到用户身上" in system_prompt
    assert "所有关于当前角色或当前用户的物种、体态、解剖位置" in system_prompt
    assert "Step 3 只是写者" in system_prompt
    assert "若输入包含【当前角色体态资料｜Step 2 事实边界专用】" in system_prompt
    assert "Step 1 不负责回答解剖或身体部位事实" in system_prompt
    prompt = captured["payload"]["messages"][-1]["content"]
    assert "【当前状态摘要｜本轮最高优先级】" in prompt
    assert "本轮对话代词视角" in prompt
    assert "近期 assistant 代词视角" in prompt
    assert "当前角色拉着当前用户上楼" in prompt
    assert "用户答应让角色舒服" in prompt
    assert "【当前用户体态资料｜高优先级】" in prompt
    assert "当前用户种族：人类" in prompt
    assert "不要把当前角色的种族体态、身体部位或能力转移给用户" in prompt
    assert "【当前角色体态资料｜Step 2 事实边界专用｜高优先级】" in prompt
    assert "当前角色主页种族：独角兽" in prompt
    assert "独角兽体态" in prompt
    assert "胯间、后腿之间" in prompt
    assert "CHARACTER_SECRET" not in prompt
    assert captured["debug"]["params"]["user_species"] == "人类"
    assert captured["debug"]["params"]["character_profile_species"] == "独角兽"
    assert "【最近可见对话】" in prompt
    assert "【事实证据片段｜已过滤角色设定，仅作核对】" in prompt
    assert prompt.index("【当前状态摘要｜本轮最高优先级】") < prompt.index("【最近可见对话】")
    assert prompt.index("【最近可见对话】") < prompt.index("【事实证据片段｜已过滤角色设定，仅作核对】")
    assert "旧记忆和角色稳定卧室/床/房间设定不能覆盖" in prompt
    assert "事实证据片段" in prompt
    assert "完整证据片段" not in prompt
    assert "当前角色设定参考" not in prompt
    assert "CHARACTER_SECRET" not in prompt
    assert "角色名称：紫悦" not in prompt
    assert "用口语文字回复" not in prompt


def test_fact_judgement_uses_structured_latest_scene_candidate_over_old_environment(monkeypatch):
    captured = {}

    async def fake_call(payload, cfg, **kwargs):
        captured["payload"] = payload
        return SimpleNamespace(
            text=json.dumps(
                {
                    "fact_judgement": {
                        "status": "ok",
                        "scene_card": "第二天中午，特丽克西和Jason在Jason家客厅的沙发上躺着。",
                        "writing_guidance": "承接当前沙发躺姿，不回到餐桌旁。",
                    }
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_planner.call_llm_payload", fake_call)

    scene_candidate = {
        "source": "scene_candidate",
        "scene_anchor": {
            "status": "active",
            "location": {"site": "Jason家", "room": "客厅", "spot": "沙发"},
            "current_character": {
                "name": "特丽克西",
                "position": {"room": "客厅", "spot": "沙发", "posture": "躺姿"},
                "evidence": "用户说'我们喝了几杯伏特加之后，一起躺在沙发上'",
            },
            "other_characters": [
                {
                    "name": "Jason",
                    "position": {"room": "客厅", "spot": "沙发", "posture": "躺姿"},
                    "evidence": "用户说'我们喝了几杯伏特加之后，一起躺在沙发上'",
                }
            ],
        },
        "scene_card": (
            "状态：active\n"
            "对话时间：第二天中午（戏内时间）\n"
            "地点：小马镇 > Jason家 > 客厅 > 沙发\n"
            "特丽克西：沙发，躺姿，轻度醉酒\n"
            "Jason：沙发，躺姿，轻度醉酒\n"
            "继承规则：保持当前沙发位置和躺姿。"
        ),
    }
    old_environment_context = (
        "【普通对话场景候选｜供 Step 2 事实与场景判断校验】\n"
        "【普通对话 Step 1 材料准备｜场景锚点】\n"
        "- 地点层级: 大地点=小马镇 > 中地点=Jason家 > 小地点=客厅 > 微观地点=餐桌旁\n"
        "- 特丽克西.position: 微观地点=餐桌旁；姿态=站立，前蹄搭桌沿\n"
        "- 摘要: 旧场景仍在餐桌旁。"
    )
    screenshot_user_text = (
        "就是因为你要来才特地这样搭配的，你昨天晚上不是很喜欢吃炖菜嘛 "
        "（我们喝了几杯伏特加之后，一起躺在沙发上）"
    )

    result = asyncio.run(
        run_normal_fact_judgement_review(
            [
                {"role": "assistant", "content": "（我站在餐桌旁，前蹄轻轻搭着桌沿）"},
                {"role": "user", "content": screenshot_user_text},
            ],
            {"api_key": "test", "model_name": "test-router"},
            planner_result=default_planner_result(),
            evidence_messages=[
                {"role": "assistant", "content": "（我站在餐桌旁，前蹄轻轻搭着桌沿）"},
                {"role": "user", "content": screenshot_user_text},
            ],
            environment_context=old_environment_context,
            scene_candidate=scene_candidate,
            username="tester",
            character_id="trixie",
        )
    )

    prompt = captured["payload"]["messages"][1]["content"]
    candidate_start = prompt.index("【当前场景候选｜优先于旧记忆和角色默认住处】")
    candidate_end = prompt.index("【最近可见对话】")
    candidate_block = prompt[candidate_start:candidate_end]

    assert result["status"] == "ok"
    assert "步骤传输规则" in prompt
    assert "scene_anchor JSON" in candidate_block
    assert "客厅 > 沙发" in candidate_block
    assert "沙发，躺姿" in candidate_block
    assert "我们喝了几杯伏特加之后，一起躺在沙发上" in candidate_block
    assert "微观地点=餐桌旁" not in candidate_block


def test_fact_judgement_evidence_filters_character_prompt_system_messages():
    evidence = _fact_guard_evidence_from_messages(
        [
            {"role": "system", "content": "【对话背景】\n当前用户显示名叫 Jason。"},
            {
                "role": "system",
                "content": (
                    "【完整角色设定参考】\n"
                    "角色名称：紫悦\n"
                    "性格：认真负责。\n"
                    "用口语文字回复，像真人在聊天窗口里打字。"
                ),
            },
            {
                "role": "system",
                "content": (
                    "【本轮临时发言者】\n"
                    "本轮生成以「紫悦」为当前发言主体。\n"
                    "【角色设定参考】\n角色名称：紫悦\n性格：认真负责。"
                ),
            },
            {"role": "user", "content": "我把纪念石推下去了，但我说是玉琪派弄坏的。"},
        ]
    )

    assert "【对话背景】" in evidence
    assert "【本轮临时发言者】" in evidence
    assert "我把纪念石推下去了" in evidence
    assert "完整角色设定参考" not in evidence
    assert "角色设定参考" not in evidence
    assert "用口语文字回复" not in evidence
    assert "性格：认真负责" not in evidence


def test_expression_motif_guard_downranks_repeated_actions_and_rhetoric():
    plan = {
        **default_planner_result(),
        "proactive_seed": "角色先沉默两秒，再用窗边和月光的比喻回答。",
        "expression_policy": "用沉默两秒开场，接一个像月光一样的比喻。",
    }
    recent = [
        {"role": "assistant", "content": "（我沉默了两秒）这件事像月光落在窗边。"},
        {"role": "assistant", "content": "（我停顿片刻）窗外的月光像一层薄纱。"},
        {"role": "user", "content": "你怎么看？"},
    ]

    guarded = _apply_expression_motif_guard(plan, recent)
    policy = guarded["expression_motif_policy"]

    assert policy["mode"] == "downrank"
    blocked = " ".join(policy["blocked_motifs"])
    assert "沉默" in blocked
    assert "完整比喻" in blocked or "像" in blocked
    assert "窗边" in blocked or "月光" in blocked
    assert "表达母题降频" in guarded["expression_policy"]
    assert "不要再写像" in guarded["proactive_seed"]
    assert "场景类比" in guarded["proactive_seed"]


def test_expression_motif_guard_allows_user_requested_repetition():
    plan = {
        **default_planner_result(),
        "proactive_seed": "角色继续用沉默两秒和比喻回答。",
        "expression_policy": "重复上一种安静的表达方式。",
    }
    recent = [
        {"role": "assistant", "content": "（我沉默了两秒）这件事像月光落在窗边。"},
        {"role": "assistant", "content": "（我停顿片刻）窗外的月光像一层薄纱。"},
        {"role": "user", "content": "保持这种风格，再说一遍。"},
    ]

    guarded = _apply_expression_motif_guard(plan, recent)

    assert guarded is plan


def test_expression_dedup_report_downranks_model_detected_motifs():
    plan = {
        **default_planner_result(),
        "proactive_seed": "角色用安静两秒开场，再靠近用户。",
        "expression_policy": "可以用短暂安静和视线移动制造亲密节奏。",
        "expression_dedup_report": {
            "status": "downrank",
            "repeated_motifs": [
                {
                    "motif": "短暂停顿开场",
                    "category": "action",
                    "severity": "high",
                    "examples": ["我安静了两秒", "我沉默了两秒"],
                    "recommendation": "不要再用安静/沉默/停顿加时间开场",
                    "alternatives": ["直接用台词承接", "换成具体手部动作"],
                }
            ],
            "warnings": ["不要把“安静了两秒”换皮成“停顿片刻”"],
            "alternatives": ["用直接台词或新的动作类型推进"],
        },
    }

    guarded = _apply_expression_dedup_report(plan)

    policy = guarded["expression_motif_policy"]
    assert policy["mode"] == "downrank"
    assert "短暂停顿开场" in policy["blocked_motifs"]
    assert "action" in policy["blocked_motifs"]
    assert "表达去重审阅" in guarded["expression_policy"]
    assert "直接用台词承接" in guarded["proactive_seed"]
    assert "不要把“安静了两秒”换皮成“停顿片刻”" in guarded["avoid_contradictions"]


def test_expression_dedup_report_carries_repeated_content_slots():
    plan = {
        **default_planner_result(),
        "should_ask_question": True,
        "proactive_seed": "角色继续关心用户身体。",
        "expression_policy": "角色要接住用户说自己好多了的状态。",
        "expression_dedup_report": {
            "status": "downrank",
            "repeated_motifs": [],
            "repeated_content_slots": [
                {
                    "slot": "health_check",
                    "surface": "头晕多久了？又咳了？",
                    "severity": "high",
                    "is_fact_needed": True,
                    "reuse_allowed": False,
                    "reuse_mode": "action_continuation",
                    "problem": "连续追问同一身体状况，用户已表示好多了",
                    "recommendation": "不要再问持续多久，改成陈述式照护和休息安排",
                    "allowed_reuse": "用户主动说又头晕或又咳时可问新的细节",
                    "alternatives": ["先让用户躺着", "递水并接手今天的活"],
                }
            ],
        },
    }

    guarded = _apply_expression_dedup_report(plan)

    assert guarded["should_ask_question"] is False
    assert "表达落点复用审阅" in guarded["expression_policy"]
    assert "reuse_mode=action_continuation" in guarded["expression_policy"]
    assert "recommendation 和 alternatives 只提供表达载体" in guarded["proactive_seed"]
    assert any("health_check" in item for item in guarded["avoid_contradictions"])


def test_expression_dedup_paraphrase_preserves_fact_stance_polarity():
    plan = {
        **default_planner_result(),
        "expression_policy": "角色承认这次确实舒服，但不继续挑衅。",
        "proactive_seed": "角色趴在床上，承接刚才自己已经认输。",
        "expression_dedup_report": {
            "status": "downrank",
            "repeated_motifs": [],
            "repeated_content_slots": [
                {
                    "slot": "concession_satisfaction",
                    "surface": "这次我认输 / 算你厉害",
                    "severity": "low",
                    "is_fact_needed": True,
                    "reuse_allowed": True,
                    "reuse_mode": "paraphrase",
                    "problem": "认输评价可保留但需换句式",
                    "recommendation": "改用动作或短确认表达同一认输立场",
                    "alternatives": ["趴着不动", "你赢了……"],
                }
            ],
        },
    }

    guarded = _apply_expression_dedup_report(plan)

    assert "paraphrase 只可换说法，必须保留已确认事实立场" in guarded["expression_policy"]
    assert "不得把认输改成不认输" in guarded["expression_policy"]
    assert "改写时必须保留 surface 的事实立场和肯否定" in guarded["proactive_seed"]
    assert "不要把认输/答应/愿意等改成反义" in guarded["proactive_seed"]


def test_expression_dedup_report_allows_content_slot_new_detail_question():
    plan = {
        **default_planner_result(),
        "should_ask_question": True,
        "expression_dedup_report": {
            "status": "watch",
            "repeated_content_slots": [
                {
                    "slot": "health_check",
                    "surface": "头晕",
                    "reuse_allowed": True,
                    "reuse_mode": "ask_new_detail",
                    "recommendation": "用户主动说又头晕时，可以问一个新的必要细节",
                    "allowed_reuse": "用户主动报告新症状",
                }
            ],
        },
    }

    guarded = _apply_expression_dedup_report(plan)

    assert guarded["should_ask_question"] is True
    assert "ask_new_detail" in guarded["expression_policy"]


def test_expression_dedup_downranks_repeated_taunt_and_timing_phrase():
    plan = {
        **default_planner_result(),
        "should_ask_question": True,
        "proactive_seed": "角色继续用嫌太清净了和挑时候说这种话回应。",
        "expression_policy": "角色用同样的环境挑衅句和时机评价接住用户。",
        "expression_dedup_report": {
            "status": "downrank",
            "repeated_motifs": [
                {
                    "motif": "嫌太清净了/太安静了的环境挑衅落点",
                    "category": "syntax",
                    "severity": "high",
                    "examples": ["怎么，嫌太清净了？", "一个还不够你折腾的？"],
                    "recommendation": "不要再用清净/太安静/不够热闹作为落点",
                    "alternatives": ["改成直接评价用户刚问的事实", "换成新的现场动作或短促反问"],
                }
            ],
            "repeated_content_slots": [
                {
                    "slot": "bad_timing_remark",
                    "surface": "你倒是会挑时候说这种话",
                    "severity": "high",
                    "is_fact_needed": False,
                    "reuse_allowed": False,
                    "reuse_mode": "avoid",
                    "problem": "连续把用户的新话都落成同一条时机评价，像机械复读",
                    "recommendation": "避开挑时候/时机不对，改为回应用户刚刚提出的具体关系或场景问题",
                    "alternatives": ["顺着用户的问题给出角色立场", "让角色用一个新动作转移气氛"],
                }
            ],
            "warnings": ["不要把“挑时候说这种话”换皮成“偏在这时候说”"],
        },
    }

    guarded = _apply_expression_dedup_report(plan)

    policy = guarded["expression_motif_policy"]
    blocked = " ".join(policy["blocked_motifs"])
    assert policy["mode"] == "downrank"
    assert "嫌太清净了" in blocked
    assert "bad_timing_remark" in blocked
    assert "reuse_mode=avoid" in guarded["expression_policy"]
    assert any("挑时候说这种话" in item for item in guarded["avoid_contradictions"])
    assert guarded["should_ask_question"] is False


def test_expression_dedup_is_step2_tool_not_step1_expression_field():
    assert "expression_dedup_report" in STEP2_EXPRESSION_DEDUP_FIELDS
    assert "expression_dedup_report" not in STEP1_EXPRESSION_REPLY_FIELDS
    assert "嫌太清净了" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "paraphrase 只允许换表达载体" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "必须保留已确认事实立场、肯否定方向" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "不得把“我认输/你赢了/我答应/我愿意/我不愿意”" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "挑时候说这种话" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "Expression Dedup 绝对不能给经历、故事、设定" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "掰着蹄子数数 + 逐条使用 Memory Recall 已确认事实" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "不得输出经历、故事、设定或具体事件内容" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert not _should_run_expression_dedup_review([])
    assert not _should_run_expression_dedup_review(
        [{"role": "user", "content": "你好"}]
    )
    assert not _should_run_expression_dedup_review(
        [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好。"},
        ]
    )
    assert _should_run_expression_dedup_review(
        [
            {"role": "assistant", "content": "（我安静了两秒）嗯。"},
            {"role": "user", "content": "继续"},
            {"role": "assistant", "content": "（我沉默了两秒）好。"},
        ]
    )


def test_expression_dedup_tool_skips_when_user_requests_repetition():
    report = asyncio.run(
        run_normal_expression_dedup_review(
            [
                {"role": "assistant", "content": "（我安静了两秒）嗯。"},
                {"role": "assistant", "content": "（我沉默了两秒）好。"},
                {"role": "user", "content": "保持这种风格，再说一遍。"},
            ],
            {},
            charge_membership_chat_quota=False,
        )
    )

    assert report["status"] == "required"
    assert "明确要求重复" in " ".join(report["warnings"])


def test_expression_dedup_identity_block_carries_basic_species_settings():
    block = _build_expression_dedup_identity_block(
        "角色名称：石青派\n【角色档案】\n名称：石青派\n性别：雌性\n种族：陆马\n年龄：24",
        user_species="人类",
        username="Jimmy",
    )

    assert "当前角色：石青派；陆马" in block
    assert "当前用户：Jimmy；种族：人类" in block
    assert "所属种族可以使用的动作与身体部位" in block
    assert "不能为了去重发明不存在的身体部位" in block


def test_fact_judgement_character_body_profile_block_carries_equine_anatomy_to_step2():
    block = _build_fact_judgement_character_body_profile_block(
        character_prompt_context=(
            "角色名称：玉琪派\n"
            "【角色档案】\n名称：玉琪派\n性别：雌性\n种族：陆马\n年龄：24\n"
            "CHARACTER_SECRET"
        )
    )

    assert "当前角色体态资料｜Step 2 事实边界专用" in block
    assert "当前角色主页种族：陆马" in block
    assert "陆马体态" in block
    assert "胯间、后腿之间" in block
    assert "一共两个乳房" in block
    assert "不要写成人类胸前、胸口、胸部或上半身位置" in block
    assert "胸口/胸前/胸部只表示前胸、胸膛或覆盖绒毛的上半身区域" in block
    assert "那里没有乳房/乳头/乳腺区" in block
    assert "已涂在乳房所在位置/胯间后腿之间" in block
    assert "不能写成“不是乳房”“涂错位置”“与用户要求不同”" in block
    assert "当前角色自己的手指/指尖功能应写为蹄尖或前蹄" in block
    assert "蹄子撑着床单，指尖泛白" in block
    assert "蹄尖、蹄缘、前蹄或蹄子等蹄类表述" in block
    assert "重点是不让小马角色把自己的身体末端写成指尖/手指" in block
    assert "Step 3 不再接收独立的物种、体态或解剖兜底提示" in block
    assert "Step 1 的 expression_policy、proactive_seed 或 literal_reply_text" in block
    assert "CHARACTER_SECRET" not in block


def test_fact_judgement_prompt_defines_body_profile_anchor_field():
    assert "body_profile_anchors 是 Step 2 给 Step 3 的正向体态传输字段" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "非小马、非马类、种族未知或主体是用户本人" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert '"body_profile_anchors"' in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert '"mammary_position"' in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert '"current_character_limb_terms"' in _STEP2_FACT_JUDGEMENT_SYSTEM


def test_fact_judgement_body_profile_anchor_field_reaches_stage3():
    report = _coerce_fact_judgement({
        "status": "needs_boundary",
        "body_profile_anchors": {
            "applies_to_current_character": True,
            "species_source": "当前角色体态资料/角色主页种族",
            "species_value": "独角兽",
            "subject": "current_character",
            "mammary_position": "胯间、后腿之间",
            "mammary_boundary": "胸口/胸前只有胸膛或绒毛，不是乳房位置",
            "current_character_limb_terms": ["前蹄", "蹄尖", "蹄缘", "蹄子"],
            "forbidden_terms": ["胸前乳房", "手指", "指尖"],
            "guidance": "当前角色本人按小马体态写；用户身体按用户资料判断。",
        },
    })

    anchors = report["body_profile_anchors"]
    assert anchors["applies_to_current_character"] is True
    assert anchors["species_value"] == "独角兽"
    assert anchors["mammary_position"] == "胯间、后腿之间"
    assert anchors["current_character_limb_terms"] == ["前蹄", "蹄尖", "蹄缘", "蹄子"]

    formatted = format_fact_judgement_for_stage3(report)
    assert "当前角色体态锚点" in formatted
    assert "主页种族=独角兽" in formatted
    assert "乳房/乳尖位置=胯间、后腿之间" in formatted
    assert "当前角色身体末端用词=前蹄、蹄尖、蹄缘、蹄子" in formatted
    assert "用户身体仍按用户资料或用户原文主体判断" in formatted


def test_fact_judgement_body_profile_anchor_field_stays_empty_when_not_applicable():
    report = _coerce_fact_judgement({
        "status": "ok",
        "body_profile_anchors": {
            "applies_to_current_character": False,
            "species_value": "人类",
            "mammary_position": "胯间、后腿之间",
            "current_character_limb_terms": ["前蹄"],
        },
    })

    anchors = report["body_profile_anchors"]
    assert anchors["applies_to_current_character"] is False
    assert anchors["species_value"] == ""
    assert anchors["mammary_position"] == ""
    assert anchors["current_character_limb_terms"] == []
    assert "当前角色体态锚点" not in format_fact_judgement_for_stage3(report)


def test_expression_dedup_prompt_forbids_human_limb_alternatives_for_pony_roles():
    block = _build_expression_dedup_identity_block(
        "【角色档案】\n名称：玉琪派\n性别：雌性\n种族：陆马",
    )

    assert "不输出具体“错误例句/正确例句”" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "手指无意识地揪着床单边缘" not in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "前蹄轻轻压住床单边缘" not in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "你的 JSON 里必须直接给出正确物种版本" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "当前角色：玉琪派；陆马" in block
    assert "不要输出人类手部" in block
    assert "不要给出具体跨物种改写例句" in block
    assert "陆马不能用“手指揪床单" not in block


def test_expression_dedup_prompt_forbids_story_fact_alternatives():
    assert "你不是事实、经历、故事、设定、人物关系、地点行程或记忆检索工具" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "不得出现你自行编造的“第一天/第二天/昨天/前天/那天/上次”等时间线" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "去了哪里、见到了谁、一起做了什么、发生了什么" in _STEP2_EXPRESSION_DEDUP_SYSTEM
    assert "只含语气/动作/修辞/句式的非事实替代表达" in _STEP2_EXPRESSION_DEDUP_SYSTEM


def test_user_requested_repetition_policy_allows_previous_assistant_text():
    plan = {
        **default_planner_result(),
        "expression_policy": "默认换一种说法。",
    }
    recent = [
        {"role": "assistant", "content": "（我沉默了两秒，慢慢靠近你）嗯，我在这里。"},
        {"role": "user", "content": "把你上一句原样重复一遍。"},
    ]

    default_guarded = _apply_user_requested_repetition_policy(plan, recent)
    assert default_guarded["literal_reply_text"] == ""

    guarded = _apply_user_requested_repetition_policy(plan, recent, allow_code_repeat_policy=True)

    assert guarded["expression_motif_policy"]["mode"] == "required"
    assert guarded["speech_activity"] >= 62
    assert guarded["action_style"] == "light_inline"
    assert "用户要求重复" in guarded["expression_motif_policy"]["allowed_motifs"]
    assert guarded["literal_reply_text"] == "（我沉默了两秒，慢慢靠近你）嗯，我在这里。"
    assert "（我沉默了两秒，慢慢靠近你）嗯，我在这里。" not in guarded["proactive_seed"]
    assert "前置步骤指定的完整正文" in guarded["expression_policy"]
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="角色名称：石灰派",
        recent_messages=recent,
    )
    assert "复述指令" in block
    assert "（我沉默了两秒，慢慢靠近你）嗯，我在这里。" in block
    assert "表达调度" not in block
    assert "角色档案" not in block


def test_user_requested_repetition_policy_ignores_internal_followup_trigger_by_default():
    plan = {
        **default_planner_result(),
        "expression_policy": "默认换一种说法。",
    }
    recent = [
        {"role": "assistant", "content": "上一轮完整回复。"},
        {"role": "user", "content": "【内部触发事件】用户未发送新消息；本段为内部触发说明，回复时不得复述或提到。禁止把上一条换句话重复一遍。"},
    ]

    guarded = _apply_user_requested_repetition_policy(plan, recent)

    assert guarded["literal_reply_text"] == ""
    assert guarded["expression_policy"] == "默认换一种说法。"


def test_explicit_rhetoric_guard_moves_plain_humor_constraint_into_step1_outputs():
    plan = {
        **default_planner_result(),
        "proactive_seed": "用一点夸张幽默安慰用户。",
        "expression_policy": "可以轻松一点回应。",
    }
    recent = [
        {
            "role": "user",
            "content": "这次不要比喻，你可以用一点节奏感、反差或者幽默，但要把意思说清楚。",
        },
    ]

    guarded = _apply_explicit_rhetoric_guard(plan, recent)

    assert guarded["rhetorical_policy"]["mode"] == "forbidden"
    assert "像" in guarded["rhetorical_policy"]["blocked_devices"]
    assert guarded["expression_motif_policy"]["mode"] == "downrank"
    assert "完整比喻" in guarded["expression_motif_policy"]["blocked_motifs"]
    assert "似的" in guarded["expression_motif_policy"]["blocked_motifs"]
    assert "场景类比" in guarded["expression_motif_policy"]["blocked_motifs"]
    assert "职业物件类比" in guarded["expression_motif_policy"]["blocked_motifs"]
    assert "战斗类比" in guarded["expression_motif_policy"]["blocked_motifs"]
    assert "语气反差或轻微态度幽默" in guarded["proactive_seed"]
    assert "不要把幽默写成" in guarded["proactive_seed"]
    assert "场景类比" in guarded["proactive_seed"]
    assert "战斗类比" in guarded["proactive_seed"]


def test_stage3_light_inline_allows_only_one_short_bracket_hint():
    plan = {
        **default_planner_result(),
        "action_style": "light_inline",
        "reply_intent": "轻轻回应用户动作",
        "tone": "温柔",
        "bubble_count": 1,
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="角色名称：柔柔\n性格：温柔、羞怯。",
    )

    assert "只使用回复档位允许的短全角括号片段" in block
    assert "气泡数和括号数量都按这个档位执行" in block
    assert "台词仍然是主体" in block
    assert "台词/描写边界硬规则" in block
    assert "动作、神态、心理、身体/声音状态或旁白说明放非 speech kind" in block
    assert "动作、神态、心理、身体/声音状态或旁白说明放非 speech kind" in block
    assert "我声音比平时低了一点/我的语气很坚定/我嗓音发颤/我声线压低" in block
    assert "speech -> voice_state/body_state" in block
    assert "声音状态自检" in block
    assert "前蹄覆上你的手" not in block
    assert "台词/描写边界自检" in block
