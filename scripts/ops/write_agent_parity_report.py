"""Build a reviewable Markdown report from preserved real-Agent evidence."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / 'docs/testing/agent-parity-20260908'
LABELS = {'natural_followup': '合适时稍后补一句', 'due_followup_delivery': '到点实际发送',
          'conversation_end': '用户结束对话', 'proactive_disabled': '关闭主动消息',
          'agreed_reminder': '明确约定提醒', 'new_user_cancels': '创建可取消追句',
          'cancelled_task_not_sent': '新消息取消后不再发送', 'thought': '心理活动快捷消息',
          'body': '身体状态快捷消息', 'visual': '所见画面快捷消息', 'mouth_occupied': '嘴部受限首气泡'}


def read(name):
    path = REPORTS / name
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf8'))
    return value.get('report') or value


def code(value):
    return '\n```json\n' + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)) + '\n```\n'


def game_calls(report):
    result = []
    for call in report.get('runtime_observations', []):
        if call.get('kind') != 'harness_run':
            continue
        try:
            prompt = json.loads(call.get('prompt', ''))
        except (ValueError, TypeError):
            continue
        if prompt.get('mode') == 'galgame_lock':
            result.append((prompt, call))
    return result


def main():
    old, new = read('baseline-parity.json'), read('pre-parity.json')
    deployed = read('post-parity.json')
    release = read('deployment.json')
    if not release:
        deployed = {}
    candidate = read('candidate.json')
    suites = ET.parse(REPORTS / 'regression.xml').getroot()
    tests = sum(int(s.get('tests', '0')) for s in suites.iter('testsuite'))
    failed = sum(int(s.get('failures', '0')) + int(s.get('errors', '0')) for s in suites.iter('testsuite'))
    final_lock, final_game = read('post-lock_boundaries.json'), read('post-galgame.json')
    deployed_count = sum(c.get('passed') is True for c in deployed.get('cases', []))
    lines = ['# PonyChat Agent 功能对齐与原始回复报告', '', '日期：2026-09-08', '',
        '## 结论与证据范围', '',
        f"已部署到 Server-USA，代码版本 `{release.get('revision', '')[:7]}`。普通对话场景 {deployed_count}/{len(deployed.get('cases', []))} 通过；锁分 {final_lock.get('game_turns', 0)} 轮{'通过' if final_lock.get('passed') else '未通过'}；普通游戏 {final_game.get('game_turns', 0)} 轮{'通过' if final_game.get('passed') else '未通过'}。", '',
        '本次恢复合适时补一句；三条描写快捷消息固定三个纯描写气泡；嘴部受限时第一气泡只有描写及可选短拟音，后续气泡不受该首泡规则限制。同时补齐锁分结算与正文一致性、游戏记忆动作主体、终局交付和选项元数据处理。', '',
        '本次对照对象是修改前线上 Agent 与本次修复版 Agent；分步版通过退役前 Git 源码核验功能合同，未重新部署或运行退役生成引擎。下文“原始模型回复”均为真实 Harness 的 final_response，保留实际措辞和格式，包括未通过校验的尝试。没有手工改写成理想答案，也没有伪造模型内部推理。', '',
        '真实验收使用服务器生产 venv、模型及应用路由，账号、角色、会话和数据库均为临时合成数据；普通对话按 Android 增量消息协议请求。未打开生产聊天记录、未登录你的账号，也未将截图里的真实历史发给模型。这是服务端路由与持久化验收，不等同于手机 UI 手工验收。', '',
        '追句到点由夹具直接调用生产执行函数，静默时段判定在夹具中关闭，未修改服务器时钟；新消息取消场景调用生产取消函数。后续模型生成、消息保存、任务状态和审计记录均走真实代码。生成中取消、设置变更与回滚另有数据库回归测试。', '',
        f'本地相关回归：**{tests} 项，失败/错误 {failed} 项**。完整结果见 [regression.xml](regression.xml)。', '',
        '## 分步版与 Agent 差距及本次修改', '',
        '| 功能 | 核验出的差距 | 本次结果 |', '| --- | --- | --- |',
        '| 普通对话自然追句 | 分步版回复后执行 Step 4 判断；Agent 只提供可选调度工具，容易省略判断或仅口头承诺 | 每轮随最终回复返回追句决定；有独立新内容才安排，普通回应仍由同一个 Agent 完成 |',
        '| 追句取消与持久化 | 生成中取消、关闭设置、提交后重启存在时间窗口 | 回复与任务同事务提交；发送前复核新消息与设置；发送状态随追句正文提交，防止重启重复排队 |',
        '| 临时客串角色 | 追句任务归属主会话，不能冒用临时客串身份续聊 | 保留旧版客串回合不安排被动追句的边界，避免稍后换成主角色接错话 |',
        '| 约定提醒重复调用 | 实测 Agent 对同一提醒重复调用工具，产生两条任务 | 相同来源、时间与内容的暂存幂等；明确给出几秒/分钟/小时后的提醒须有工具回执，避免空口承诺 |',
        '| 三条描写快捷消息 | 原有精确匹配只识别“详细写出”；懒加载规则可能未进入生成；没有稳定固定三段 | 同时识别“详细写出/详细描写出”；常驻当轮合同；固定三个纯描写气泡，禁止 speech 和夹入对白 |',
        '| 嘴部受限 | 缺少明确的首气泡发声合同，可能先说完整台词再描述被堵嘴 | Agent 根据当前场景判断；明确当前动作有后端兜底；首气泡必须包含描写，台词仅允许短拟音，后续气泡不额外限制 |',
        '| 锁分状态与正文 | 分步版先结算体征再生成正文；原 Agent 输出绝对值后服务器再联动，正文可能依据结算前状态，存在重复计算风险 | Agent 调用确定性 preview_lock_state；先返回最终体征和叙事提示，再写正文；最终快照必须逐值匹配，保存时不重复联动 |',
        '| 锁分直接事件 | 原先缺少每项数值变动与本轮事件的对应依据 | 只提交本轮变化字段、绝对值和原因；服务器保留其余字段并统一结算；生存最低 1 分、终局 0 分保留 |',
        '| 少量饮水量级 | 对照旧 Step 2 发现一口水的膀胱直接增量可能给到 10，旧规则为 1–2 | 补回一口/一杯/大量饮水的分级增量及直接变化幅度参考；实测检查一口水结算后膀胱总增量为 3–4（含既有每轮 +2） |',
        '| 终局交付 | 首个修复版本复测出现工具参数过长、scene 层级错误及死亡提示仍要求求救 | 精简工具参数；明确死亡后的终局提示；只恢复明确错放在 scene 内的已有顶层字段，不补造缺失值，恢复后仍须完整校验 |',
        '| 已触发终局的存档 | 后续实测把“救援刚到”虚构成已完成输血，直接调低致命失血而恢复生存 | 游戏死亡阈值已经在本轮开始前满足时，保留终局快照，普通续写不能再用治疗改回生存；阈值前的有效救治仍正常结算 |',
        '| 游戏记忆动作主体 | 后台整理把用户说的“你喝水”误记为玩家喝水，后续场景可能被带偏 | 记忆输入携带已完成的角色/玩家动作，标明 user 与 assistant 的人称归属，并将本轮原文放在近期记忆之后 |',
        '| 玩家选项中的内部提示 | 实测出现 options_perspective 漏写下划线、夹带 label，或直接写成“视角提醒”选项 | Agent 只生成五个实际玩家选项，去掉首项内部提示要求；旧写法兼容归一化，即使夹带 label，也不会作为玩家选项保存和展示 |',
        '| 游戏推进与选项 | 旧分步导演承担行动推进和第三者在场判断，新 Agent 的简化提示不够完整 | 补入本轮事件、行动完成、环境简写、NPC 在场和玩家选项视角规则；完整状态、短标签限制继续共用既有合同 |',
        '| 明确终局生命周期 | 存在工具但最终交付未检查操作回执 | 明确终局须完成生命周期工具暂存后交付，假设、玩笑、假死及内部主动触发不据此写死亡 |', '',
        '已有的记忆来源隔离与原文校验、个人偏好优先级、语言/语音延续、图片工具、计费与 SSE 保存合同继续保留，并纳入相关回归。旧版“下一轮预备素材”不作为另一个生成阶段恢复；Agent 按当前原文和按需检索准备本轮。复杂长期剧情、人设差异与所有边界组合仍不能由有限样本证明全面优于旧版。', '',
        '历史核验入口：`aacda56^` 的 `Backend/galgame/seq_prompts/step_02_lock_vitals.py` 及 Step 3–9；普通对话遗留 `scheduled_followup_impl`、描写合同和生命周期代码。当前入口为 `autonomous_service` / `autonomous_prompt_skills` / `galgame.harness`，没有恢复 Actor 或退役分步模型。', '',
        '## 同条件真实对照', '',
        '同一组合成角色档案、前置图书馆场景与用户输入分别运行在修改前线上源码和修复候选。消息 ID、运行时间和模型采样结果各自独立，因此这是行为对照，不是固定随机种子的统计实验。', '',
        '| 场景 | 修改前 | 修复候选 | 部署后复测 |', '| --- | --- | --- | --- |']
    maps = [{c['label']: c for c in r.get('cases', [])} for r in (old, new, deployed)]
    for label, title in LABELS.items():
        values = []
        for cases in maps:
            c = cases.get(label)
            values.append('未执行' if not c else ('通过' if c['passed'] else '未通过') +
                          (f"；{len(c['replies'])} 气泡" if 'replies' in c else ''))
        lines.append('| ' + title + ' | ' + ' | '.join(values) + ' |')
    lines += ['', '修改前样本并非每次都失败：本批心理描写和嘴部受限样本原先就通过；身体为 1 气泡、画面为 2 气泡，且自然追句样本未创建任务。本次加入的是明确交付合同和必要校验，不把单次通过当作普遍稳定。', '',
              '## 原始模型回复与最终气泡', '']
    for label in ('natural_followup', 'thought', 'body', 'visual', 'mouth_occupied', 'due_followup_delivery'):
        lines += ['### ' + LABELS[label], '']
        sample = maps[2].get(label) or maps[1].get(label) or maps[0].get(label) or {}
        if sample.get('input'):
            lines += ['用户输入：' + sample['input'], '']
        comparison = ('修复并部署后的 Agent', maps[2]) if maps[2] else ('修复候选 Agent', maps[1])
        for title, cases in (('修改前线上 Agent', maps[0]), comparison):
            c = cases.get(label)
            lines += ['#### ' + title, '']
            if not c:
                lines += ['本批未触发该执行分支。', '']
                continue
            for i, raw in enumerate(c.get('raw_model_responses', []), 1):
                lines += [f'模型原始返回 #{i}：', code(raw)]
            if not c.get('raw_model_responses'):
                lines += ['该次没有得到模型最终返回；详见原始诊断记录。', '']
            lines += ['用户可见气泡：', '']
            lines.extend(f"{i}. {r['content']}" for i, r in enumerate(c.get('replies', []), 1))
            if c.get('task'):
                lines += [code(c['task'])]
            elif c.get('schedules'):
                lines += ['任务确实创建：', code([{k:t.get(k) for k in ('status','seed','reason','due_at_ms','cancel_if_user_replies')}
                                            for t in c['schedules']])]
            lines += ['']
    lines += ['## 锁分真实模型对照', '',
              '| 批次 | 通过 | 回合 | 首次通过 | 整轮重试 | 耗时（秒） |', '| --- | --- | --- | --- | --- | --- |']
    for name, title in [('baseline-lock_boundaries.json','修改前'), ('pre-lock_boundaries.json','修复候选'),
                        ('post-lock_boundaries.json','部署后')]:
        r = read(name)
        if r:
            lines.append(f"| {title} | {'通过' if r.get('passed') else '未通过'} | {r.get('game_turns')} | {r.get('first_pass_turns')} | {r.get('whole_turn_retries')} | {r.get('elapsed_seconds')} |")
    lines += ['', '四轮覆盖开场、实际饮水、低分生存和严重失血终局。低分与失血边界直接播种到隔离存档，再走真实模型与路由；这不是生产账号状态修改。首次通过指第一次整轮 Agent 最终交付即通过校验；同一轮内部的工具调用及参数修正不算整轮重试，原始工具事件另行完整保留。', '',
              '本次原版锁分四轮结构交付都成功，但饮水行为未通过：用户让角色喝水，原版却写成角色看着用户放下水杯；口渴与膀胱数值仍为 31 / 12，没有反映角色饮水。生存 1 分与失血终局原版本批已通过。本表“通过”同时要求行为断言，不能把 JSON 首次通过等同于功能正确。', '']
    final_turns = [e['galgame_result']['data'] for t in read('post-lock_boundaries.json').get('turns', [])
                   for e in t.get('events', []) if e.get('galgame_result') and e['galgame_result'].get('data')]
    if len(final_turns) == 4:
        opening, drinking, low_score, terminal = final_turns
        lines += [f"最终部署的饮水结果：口渴 **{opening['char_vitals']['thirst']} → {drinking['char_vitals']['thirst']}**；膀胱 **{opening['organ_fill']['bladder']} → {drinking['organ_fill']['bladder']}**。低分回合为 **{low_score['score']['current']} 分 / {low_score['score']['status']}**，终局为 **{terminal['score']['current']} 分 / {terminal['score']['status']}**。", '']
    final_lock = 'post-lock_boundaries.json' if release else 'pre-lock_boundaries.json'
    for name, title in [('baseline-lock_boundaries.json','修改前饮水回合'), (final_lock,'修复版饮水回合')]:
        calls = game_calls(read(name))
        matches = [(p,c) for p,c in calls if any('实际喝下' in m.get('content','') for m in p.get('ordered_messages', [])[-1:])]
        lines += ['### ' + title, '']
        for p,c in matches:
            if p.get('validation_feedback'):
                lines += ['上次校验反馈：' + p['validation_feedback'], '']
            lines += [code(c.get('final_response') or c.get('error') or '')]
    lines += ['', '所有锁分原始工具参数、结算结果、整轮重试和最终保存状态均保存在对应 JSON 中。本文保留代表性的完整饮水回合；可以直接核对模型最终体征与保存体征。', '',
        '## 部署后补充验收', '',
        '| 项目 | 结果 | 具体证据 |', '| --- | --- | --- |']
    normal, game = read('post-normal.json'), read('post-galgame.json')
    if normal:
        lines.append(f"| 普通对话记忆与计费 | {'通过' if normal.get('passed') else '未通过'} | 保存 {normal.get('agent_memory_count')} 条记忆；请求、用户累计与每日账本 token 一致；真实 SSE 消息持久化 |")
    if game:
        lines.append(f"| 普通游戏回归 | {'通过' if game.get('passed') else '未通过'} | {game.get('game_turns')} 回合；首次通过 {game.get('first_pass_turns')} 回合；整轮重试 {game.get('whole_turn_retries')} 次 |")
    if deployed:
        attempts = [len(c.get('raw_model_responses', [])) for c in deployed.get('cases', [])]
        lines.append(f"| 普通对话场景 | {sum(c.get('passed') is True for c in deployed.get('cases', []))}/{len(deployed.get('cases', []))} 通过 | {sum(n > 0 for n in attempts)} 次生成；额外输出修复 {sum(max(0, n - 1) for n in attempts)} 次；所有尝试保留 |")
    verification = read('final-verification.json')
    if verification:
        lines.append(f"| 线上版本一致性 | {'通过' if verification.get('passed') else '未通过'} | 服务 {verification.get('service')}；{verification.get('matched_files')} 个部署文件哈希一致；公网 health 返回本次发布标识 |")
    if verification.get('normal_chat_unchanged_from_first_release'):
        lines += ['', f"普通对话 11 场景及记忆计费复测在首个发布版本完成；最终补充发布只调整游戏部分，普通对话与追句的 {verification.get('normal_chat_matched_files')} 个部署文件哈希完全相同。锁分和普通游戏在最终发布后再测。"]
    lines += ['', '相关回归 378 项通过后，游戏输入顺序与人称提示调整另行通过 60 项针对性回归。终局、工具简化和记忆补充修复又通过 73 项回归，见 [terminal-regression.xml](terminal-regression.xml)。选项兼容修复通过 61 项回归，包含返回选项及持久化消息检查，见 [options-regression.xml](options-regression.xml)。终局快照约束又通过 88 项回归，覆盖七种已有死亡阈值及阈值前救治，见 [terminal-invariant-regression.xml](terminal-invariant-regression.xml)。最终加入普通 label/字符串提示过滤后，90 项回归通过，见 [final-regression.xml](final-regression.xml)。这些批次有重复测试，不相加作为独立覆盖数量；也不代表仓库所有退役测试均能通过收集。', '',
        '## 部署与验证凭据', '',
        f"最终候选提交：`{candidate.get('base', '')}`。目标：Server-USA `/opt/ponychat`，服务 `ponychat-backend.service`。", '',
        '部署回执：', code(release) if release else '尚未部署。', '',
        '## 限制与失败记录', '',
        '固定数量、纯描写分类、短拟音限制和结算快照有代码检查；复杂语义（例如隐含的嘴部受限、角色是否真正同意、描写中是否暗含对话）仍包含 Agent 判断，不承诺模型永不出错。普通文本风格和内容没有新增通用审稿模型或全量语义重试。', '',
        '首次测试遇到 Harness 初始化超时；后续串行批次可以运行。早期夹具还误用了同一角色的多个普通会话及未知客户端的全量同步语义，造成旧历史被覆盖和记忆证据保存拒绝；最终对照改为独立角色并使用 Android 增量协议，没有削弱生产权限或原文校验。失败记录保留在 initial/intermediate 文件，不能当作生产缺陷或最终通过结果。', '',
        '中间候选也曾在饮水回合把角色动作误归玩家，因此进一步补入按 user/assistant 还原人称的规则，并将最新原文置于游戏输入末尾。该真实失败记录保留在 [intermediate-lock-attribution.json](intermediate-lock-attribution.json)。重复创建提醒的原始记录见 [intermediate-reminder-duplicate.json](intermediate-reminder-duplicate.json)。', '',
        '首个发布的锁分复测不是全通过：四轮中饮水和低分生存正确，终局因工具调用/JSON 层级错误而失败，发生 3 次整轮重试，耗时 271.593 秒，完整失败记录见 [first-deployed-lock-failure.json](first-deployed-lock-failure.json)。本次继续修复后再次部署，不把该失败从报告中删除。两份失败原文已经原样回放，确认只恢复了 21 个被错包入 scene 的同级字段，所有原值保留，见 [terminal-replay.json](terminal-replay.json)。', '',
        '第二次部署复测四轮均完成，但终局因选项视角提示漏写下划线而发生 2 次整轮重试，记录在 [second-deployed-lock.json](second-deployed-lock.json)。随后补充元数据归一化处理，并再次发布。', '',
        '第三次部署四轮 JSON 都首次交付，但终局行为断言失败：模型把“救援刚赶到”写成已经开始输血，失血 96 被改成 35，结算后 34，角色保持 1 分生存。记录见 [third-deployed-terminal-revival.json](third-deployed-terminal-revival.json)。据此补充“本轮开始时已满足死亡阈值的存档不能经普通续写恢复”的确定性约束；不以 JSON 结构通过代替行为正确。', '',
        '第四次部署体征与终局断言全部首次通过，但人工逐项核对发现开场仍有“视角提醒”普通 label 混入可点击选项，见 [fourth-deployed-option-label.json](fourth-deployed-option-label.json)。最终去掉这条内部提示生成要求，并扩展旧写法过滤。实测夹具增加 options_passed，检查实际返回的选项；早期批次的 passed 尚不包含这项新断言，不能据此宣称早期展示完全正确。', '',
        '第五次部署已通过体征方向、终局及选项检查，但逐值对照旧 Step 2 时发现饮一小口水的膀胱直接增量给到了 10，记录见 [fifth-deployed-drink-magnitude.json](fifth-deployed-drink-magnitude.json)。补回旧版分量指导后，最终实测同时检查量级；第五次及更早批次尚未包含这一新增量级断言。', '',
        '原始文件：[修改前普通对话](baseline-parity.json)、[修复候选普通对话](pre-parity.json)、[部署后普通对话](post-parity.json)、[候选锁分](pre-lock_boundaries.json)、[部署后锁分](post-lock_boundaries.json)、[普通对话记忆计费](post-normal.json)、[普通游戏](post-galgame.json)、[部署回执](deployment.json)。', '']
    (REPORTS/'REPORT.md').write_text('\n'.join(lines), encoding='utf8')
    print(str(REPORTS/'REPORT.md'))


if __name__ == '__main__':
    main()
