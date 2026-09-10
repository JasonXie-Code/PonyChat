"""Render saved, synthetic acceptance evidence without rewriting model replies."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/normal-reliability-20260908'


def read(name):
    path = OUT / name
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else {}


def report(name):
    return read(name + '.json').get('report', {})


def count(value):
    cases = value.get('cases', [])
    return str(sum(bool(c.get('passed')) for c in cases)) + '/' + str(len(cases))


def main():
    deployment = read('deployment.json')
    baseline, candidate = report('baseline'), report('pre-reliability')
    recovery, parity = report('pre-recovery'), report('pre-parity')
    post = report('post-recovery')
    android = read('android-tests.json')
    semantic = read('semantic-review.json')
    lines = [
        '# Agent 可靠性修复、三种模式验收与原始回复', '',
        '日期：2026-09-08。范围：普通对话、普通游戏（galgame）、游戏锁分（galgame_lock）。', '',
        '本报告承接[前一轮分步版功能对齐报告](../agent-parity-20260908/REPORT.md)，补充锁屏丢回复、运行中追加消息、人类用户身体部位和计划被当成既成事实的问题。前一轮已完成的追句、描写快捷消息、首气泡禁说话、游戏结算与剧情合同，本轮再次验证。', '',
        '## 发布状态', '',
        (f"已部署 Server-USA，代码提交 `{deployment['revision']}`，发布标记 `{deployment['release']}`。"
         if deployment else '代码与候选验收已准备，部署回执尚未生成。'), '',
        'Android 5.6.27（367）已构建并发布签名 APK。客户端恢复判断需要安装此版本；服务端断线后继续生成对现有客户端也生效。', '',
        '[下载 5.6.27](https://www.ponychat.org/releases/PonyChat-v5.6.27-367-release.apk)。安装包、远端副本及公网下载的 SHA-256 均为 `c3cbdfbf7edd36796d4dbcd1953f5a3f9b1a27933c7a43f2bf1845a5db048a7c`。', '',
        '## 问题证据与实际改动', '',
        '| 项目 | 核验结果 | 改动 |',
        '| --- | --- | --- |',
        '| 普通对话锁屏无回复 | 18:20:23 的中文重写请求在 18:20:34 被取消；18:23:15 重发后才在 18:23:26 保存回复。不是单纯列表漏刷新。 | accepted 前先保存用户消息、创建受跟踪任务；服务端完整执行生成及后续惰性保存。关闭连接只停止该订阅。 |',
        '| 生成中补充消息 | 原有版本令新请求作废旧 generation token，导致旧工作被取消。 | 同用户、同角色的开放任务复用当前 Agent；补充先落库，再经 SDK session/prompt 进入同一会话。接收与完成边界互斥，等待补充输入回执，避免旧 idle 信号提前结束。 |',
        '| 重连、重传 | 连接重建不能再代表新生成。 | 可重新订阅已有输出；相同 message_id 去重，成功交付的近期请求可重放，失败结果不进入成功缓存。缓存有 5 分钟、64 项上限。 |',
        '| 用户被写成蹄子 | 线上共享资料已是人类，模型输入也有该资料；错误发生在人称与身体部位归属。 | 将共享用户资料与角色档案分开绑定，并把身体归属规则放入压缩后仍常驻的 Agent 指令。保留用户明示变身、反向物种组合和资料不共享边界。 |',
        '| 枕头下面凭空有芝士 | 较早原话表达“回家后还想藏到枕头底下”，18:44:23 却写成“还藏着呢”。愿望被升级成已完成事件。 | 区分愿望、约定、取得、放置、消耗与既成事实；时间过去或开始回家不构成计划完成证据。允许自然新动作，避免无根据回填旧库存。 |',
        '| 普通游戏和锁分锁屏 | 两种游戏共用 SSE finally；旧代码断线后等待 5 秒就取消任务。 | 两种模式均在返回响应前创建后台任务；生成、校验、保存、结算和解锁由任务持有，断线只清理连接队列。 |',
        '| 游戏解锁恢复 | 客户端只检查最后一条完整助手消息，可能将上一轮误判为本轮已完成。 | 保留本轮用户消息 ID、时间锚点，检查对应后续回复；旧历史、流式占位、错误消息不结束恢复。切换角色或会话时退出旧轮询。 |',
        '| 运行环境冷启动 | 实测有几次 SDK 在模型调用前超过旧 30 秒初始化上限，未产生模型正文。 | 两种运行方式均容许最多 60 秒冷启动，仍受总回合时限约束；没有通过重新发起模型回合来掩盖超时。 |', '',
        '用户没有停止当前生成的入口，本次没有新增这种权限或停止流程。普通对话旧客户端恢复时发来的 cancel/unlock 不再取消开放的 Agent。尚未触发的旧追句可因新用户消息失去意义而取消；这与终止当前 Agent 是两件独立的事。', '',
        '## 验收结果', '',
        '| 验收 | 结果 | 边界 |',
        '| --- | --- | --- |',
        f'| 后端相关回归 | 424 项通过，1 项明确排除 | 覆盖 Agent、SDK、持久化、身份共享、普通游戏/锁分及新增断线竞态。 |',
        f"| Android 单元测试 | {android.get('tests', 0)} 项通过 | 包括 4 项当前回合恢复判断；Release 构建成功。 |",
        f'| 身份、事实状态、普通对话断线 | {count(candidate)} | 服务端真实模型、真实路由和临时数据库；具体语义另见下表。 |',
        f'| 普通对话补充、普通游戏恢复、锁分恢复 | {count(recovery)} | 两种游戏分别开场、续轮断线、保存、两次拉取，并核对结算不变。 |',
        f'| 追句、提醒、三种描写、嘴部受限 | {count(parity)} | 追句到点由夹具调用真实执行函数；没有改变生产时钟或用户设置。 |',
        f"| 部署后实际源码复测 | {count(post) if post else '待写入回执'} | 使用已部署源码，不覆盖候选；仍采用独立临时数据。 |", '',
        '两个旧测试入口存在既有问题：`test_scheduled_followup_prompting.py` 引用仓库中已不存在的拆分测试文件；`test_stage2_memory_loaders_respect_memory_enabled_switch` 仍查找已退役的 Step 2 函数。首次完整命令的错误保留在验收文件中，最终相关命令明确排除了这两处，不能称为整个仓库所有测试通过。当前 Agent 的记忆与共享边界由对应新路径测试覆盖。', '',
        '新增断线测试分别覆盖生成前、生成中、保存中，普通游戏和锁分各运行一遍；流关闭后断言仍只保存一次、保存完成后才释放锁。真实恢复测试则通过 /api/conversation/detail 拉取两次，比较消息、分数与锁分状态未再变化。', '',
        '真实模型测试不读取生产聊天数据库。生产日志只用于用户指定问题的只读核验；合成账号、角色和历史位于临时数据库，未修改 Jason 的资料、聊天或游戏存档。', '',
        '## 新消息如何进入同一个 Agent', '',
        '首条请求：“我们现在在街口，我原本想去河边散步。你想陪我去吗？”连接在 accepted 后关闭。Agent 已开始后，再提交：“补充一下，我改主意了，现在去图书馆，不去河边。请用中文回应。”', '',
    ]
    first = next((c for c in recovery.get('cases', []) if c.get('mode') == 'normal'), {})
    lines += [f"实测 Agent 调用 {first.get('agent_invocations')} 次；补充输入取得 SDK 回执；同 ID 重传后仍为 {first.get('agent_invocations_after_replay')} 次。SDK 内部调用模型 2 次，因为已在进行中的一次推理不能倒写输入，下一步使用原会话继续。没有重建 Agent，也没有声称每条补充都不再消耗任何 token。", '']
    lines += ['实际交付：', ''] + ['> ' + str(s) for s in first.get('replies', [])] + ['']
    lines += ['## 同条件前后对照', '',
        '以下取未修改线上源码与候选源码的真实运行结果。对照的角色、历史和用户输入相同，消息 ID、时间和采样各自独立。不是固定种子实验，也不是重新运行已退役分步引擎；分步系统的合同来源及前次差距见前一轮报告。', '',
        '| 场景 | 修改前交付 | 修改后交付 | 人工核验原文 |', '| --- | --- | --- | --- |']
    prior = {c['label']: c for c in baseline.get('cases', [])}
    for c in candidate.get('cases', []):
        b = prior.get(c['label'], {})
        lines.append(f"| {c['label']} | {'成功' if b.get('passed') else '未完成'} | {'成功' if c['passed'] else '未完成'} | {semantic.get(c['label'], '')} |")
    lines += ['', '表格的“交付成功”仅表示生成、保存和同步完成，不能代替语义判断。修改前 human_hand_and_unfinished_plan 虽然成功交付，却明确把拟藏的芝士写成已在枕头下面。没有模型输出的失败例不用于判断模型文风或事实能力。', '',
        '## 原始模型正文与实际气泡', '',
        '以下 final_response 按实测原文写入，不手工改成理想答案。只有最终输出，没有模型隐藏推理。格式失败、初始化失败及其它尝试保留在同目录 JSON 验收记录中。', '']
    for c in candidate.get('cases', []):
        lines += ['### ' + c['label'], '', '用户输入：' + c['input'], '', '前置历史：', '']
        for role, text in c.get('history', []):
            lines += ['> ' + role + '：' + text, '']
        for title, value in [('修改前', prior.get(c['label'], {})), ('修改后', c)]:
            lines += ['**' + title + '**', '']
            raw = value.get('raw_model_responses', [])
            if not raw:
                lines += ['未取得模型最终正文；接口结果见验收 JSON。', '']
            for model in raw:
                lines += ['```json', str(model.get('final_response') or ''), '```', '']
            lines += ['实际保存气泡：', '']
            lines += ['> ' + str(m['content']) + '\n' for m in value.get('replies', [])] or ['无。', '']
    lines += ['## 本轮快捷消息与首气泡复测原文', '']
    for c in parity.get('cases', []):
        if c.get('label') not in ('thought', 'body', 'visual', 'mouth_occupied', 'natural_followup', 'due_followup_delivery'):
            continue
        lines += ['### ' + c['label'], '']
        for model in c.get('raw_model_responses', []):
            lines += ['```json', model, '```', '']
        lines += ['实际保存：', ''] + ['> ' + str(m.get('content', '')) + '\n' for m in c.get('replies', [])]
    lines += ['## 普通游戏与锁分恢复时的原始输出', '',
        '以下为候选恢复测试的真实开场、续轮及必要格式修订输出；续轮在收到生成步骤事件后断开连接。完整存档和两次拉取结果见 pre-recovery.json。', '']
    for c in recovery.get('cases', []):
        if c.get('mode') not in ('galgame', 'galgame_lock'):
            continue
        lines += ['### ' + c['mode'], '',
            f"助手消息从 {c['assistant_count_before']} 条变为 {c['assistant_count_after']} 条；重复拉取后状态不变：{c['stable_after_repeated_pull']}。", '']
        for model in c.get('raw_model_responses', []):
            lines += ['```json', str(model.get('final_response') or model.get('error') or ''), '```', '']
    lines += ['## 范围与剩余限制', '',
        '- 已核验手机协议的断线、重连、数据库持久化及拉取，未执行手机硬件上的手动锁屏/解锁演练。需要安装 5.6.27 才能获得本次客户端恢复判断修复。',
        '- 任务由当前服务进程持有；本次保证网络断开不会取消任务，不等同于服务器突然断电、进程崩溃后自动续跑。已有正常停机等待机制继续使用。',
        '- 新消息在 Agent 仍生成时进入同一会话；已完成并封口、正在保存交付的结果不会被倒写，新输入会等待该交付完成后继续。',
        '- 人称、物品状态规则已进入真实模型输入，有限样本通过不代表所有自由剧情永远不幻觉。本轮一个候选仍用了偏拟人的“反手”措辞；没有声称完全消除所有解剖表达问题。',
        '- 未重新运行退役分步系统，也未统计所有场景的延迟/token 降幅，不能据有限样本宣称所有功能全面优于分步版。已修复问题与实际验证结果逐项列出。', '',
        '## 证据文件', '',
        '- [修改前原始结果](baseline.json)、[候选身份与断线结果](pre-reliability.json)、[三模式恢复结果](pre-recovery.json)、[追句与描写回归](pre-parity.json)。',
        '- [后端最终回归](backend-tests-final.txt)、[首次回归旧测试错误](backend-tests.txt)、[Android 测试](android-tests.json)。',
        '- 调试期间 SDK 导入路径错误、测试夹具未开锁分权限、冷启动超时等记录保留为 `*-attempt*.json`，未混入最终通过数。',
        '- SDK 接口依据：[DeepSeek Harness Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)，实际兼容目标为服务器安装的 0.1.2rc1；运行中补充和回执行为另有真实会话与竞态回归验证。', '']
    if deployment:
        lines += [f"- [部署回执](deployment.json)，回滚备份：`{deployment['backup']}`。代码、原部署标记、应用版本环境文件及 SQLite 快照均在该目录。", '']
    if post:
        lines += ['- [部署后恢复复测](post-recovery.json)。', '']
    download = read('public-download.json')
    if download:
        lines += [f"- [正式下载入口验收](public-download.json)：`/download/apk` 原先仍指向 5.6.26，现已更新为 5.6.27，并验证完整文件哈希。nginx 修改前备份：`{download['nginx_backup']}`。", '']
    if read('post-source-verification.json'):
        lines += ['- [部署后源码校验](post-source-verification.json)：15 个后端文件 SHA-256 与部署提交一致，服务 active。', '']
    (OUT / 'REPORT.md').write_text('\n'.join(lines), encoding='utf8')


if __name__ == '__main__':
    main()
