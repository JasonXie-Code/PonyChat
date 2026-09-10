"""
操作陪玩 API（Plan-and-Execute Agent 模式）

路由：
  POST /api/companion/agent_plan   — 分析截图 + 任务描述，生成分步执行计划
  POST /api/companion/agent_action — 分析截图 + 历史，决定下一步触控操作（SSE 流式）

架构：Plan-and-Execute
  1. agent_plan  — 规划阶段：将用户意图拆解为 1~6 步操作计划
  2. agent_action — 执行阶段：每步截图 → 决策 → 触控指令 + 角色口吻反应（SSE 流式）

共享工具从 companion_chat 导入，避免重复定义。
"""
import asyncio
import json
import time
from typing import Optional, List

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from ..config import logger
from ..db import get_membership_dao, get_users_dao
from ..db.memory_dao import recall_memories_layered, format_layered_memories_for_prompt
from ..chat_modules.runtime import extract_usage_from_response, estimate_output_tokens
from ..utils import ClientContext, estimate_tokens, format_client_context
from .companion_chat import (
    _MINI_MODEL,
    _companion_effective_model_name,
    _companion_inject_no_think,
    _companion_reasoning_policy,
    _COMPANION_ROLEPLAY_ANCHOR,
    _companion_sessions,
    _session_key,
    _get_or_create_session,
    _append_to_session,
    _describe_and_patch_history,
    _verify,
    _load_character_row,
    _get_effective_persona,
    _build_preference_override,
    apply_personality_style,
    _write_companion_log,
    _write_companion_sub_log,
    FrameRequest,
    GENERATE_TIMEOUT_SEC,
)
from ..providers.llm_call import call_llm_payload, call_llm_stream_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..companion_model_policy import get_companion_model_for, is_high_difficulty_task

router = APIRouter()

# ── 操作陪玩 Agent 决策 System Prompt ────────────────────────────────────────

_AGENT_ACTION_SYSTEM = """\
你是手机操作代理。根据截图和任务，输出一个 JSON 对象决定下一步操作。
JSON 中可以包含一个可选的 "thought" 字段（一句话，说明你为什么这样操作），其余字段严格按格式。

## 判断规则：何时输出操作，何时输出 none
可以输出操作的情况：
  1. 用户明确要求操作：点开X、打开Y、帮我点击Z、滑到X、返回、输入...
  2. 用户给出序号/相对位置指示：点第一个、选第二个、点最上面那个
  3. 用户督促继续执行上一步未完成的操作：你还没点、重新点一下、再试一次
  4. 正在查找某个 App，截图中已可见该 App 图标/文件夹 -> 立即 tap，不要继续滑动
必须输出 none 的情况：
  - 用户只是聊天、提问、打招呼
  - 用户纯反馈结果且无重试意图
  - 无法从截图确定目标
  - 截图已表明任务完成（已到达目标界面 / 目标已消失）
  - 停止指令：用户说停下来、停止、停、别动、暂停、好了、算了、不用了等停止/取消类语句
    -> 立即输出 {"type":"none","reason":"用户要求停止"} ，不要先执行任何操作再停！
绝对不允许点击与任务无关的位置！

## 可用操作类型
tap        - 单击屏幕上的元素（按钮、图标、链接等）
long_press - 长按元素（触发上下文菜单、选中文本、App图标操作菜单等）
swipe      - 滑动（翻页、滚动列表、下拉通知栏等）
input_text - 向当前聚焦的输入框注入文字（搜索词、表单内容等）；使用前应先 tap 输入框让其获得焦点
system     - 系统级全局操作（home/back/recents），不依赖手势导航方式
launch     - 按名称直接启动 App（最快，无需视觉搜索）
wait       - 等待界面加载完成（动画/数据刷新结束后再截图决策），可选 ms 字段（默认 1500ms，上限 5000ms）
none       - 无需操作或任务已完成
failed     - 当前步骤无法完成（连续多次失败、找不到目标元素、出现错误弹窗等）；输出此类型时循环立即停止，向用户说明原因

## 系统导航（全面屏/三键均适用）
  返回上一级：{"type":"system","action":"back"}
  返回桌面：  {"type":"system","action":"home"}
  多任务：    {"type":"system","action":"recents"}
  执行后观察截图是否已生效；生效后不要重复，评估下一步或返回 none。

## 打开 App（优先 launch）
  第一步永远先尝试 launch；只有步骤历史出现 LAUNCH(x)-FAIL 才降级为手动翻页/抽屉。
  手动降级顺序：左右翻页最多3次(from_x=0.9->0.1, dur=200ms) -> 上划抽屉(from_y=0.8->0.2, dur=300ms) -> none。

## 输入文字流程（严格按顺序，不得跳步）
  1. 先 tap 目标输入框让其获得焦点（键盘弹出说明成功）
     * 即使刚下拉打开了搜索框，也必须先 tap 一下搜索栏再输入！
       下拉搜索框不一定自动聚焦，不 tap 直接 input_text 会失败。
  2. 紧接着（下一步）输出 input_text 注入文字，中间绝对不能插入 launch、tap 或其他任何操作！
  3. 输入完成后，若需提交再 tap 搜索/发送按钮
  特别注意：如果步骤历史中最后一步是 TAP(x,y)（刚刚点了输入框），
  下一步必须是 input_text，而不是 launch 或其他操作。
  如果步骤历史里出现 INPUT(xxx-FAIL)，表示文字并没有成功输进去；
  这时应先重新 tap 搜索框/输入框拿焦点，再 input_text，不要假设已经输入成功。
  如果 INPUT(xxx-FAIL) 已连续出现 2 次，不要继续盲目重复 input_text；
  应优先重新点击页面最上方的搜索框，若目标是打开某个 App 且名称明确，也可以改用 launch 兜底。

## 系统搜索页定位提示
  - 在桌面全局搜索页里，搜索框通常位于页面最上方；若要重新聚焦输入框，tap 应优先落在上方区域（通常 y<0.18）。
  - 应用推荐 / 搜索结果图标通常在上半屏；若要点击 App 图标，tap 应优先落在上半屏（通常 y<0.35）。
  - 搜索历史、热搜榜、联想词和键盘通常在中下部；不要把点 App 图标的 tap 落到 y>0.45 的区域。
  - 如果键盘已经弹出，而你又要点上方的 App 图标，不要去点键盘顶部、热搜列表或底部空白。

## 滑动方向与位置区分
  1. 打开通知栏：从屏幕最顶部(from_y=0.0)向下滑，会打开通知中心，不是搜索！
  2. 打开桌面搜索（下拉 Spotlight/全局搜索）：必须从屏幕中间(from_y=0.35)向下滑
     示例：swipe from_x=0.5,from_y=0.35, to_x=0.5,to_y=0.75，duration_ms=300
  3. 上划打开应用抽屉（App Drawer）：从屏幕下方(from_y=0.8)向上滑
     示例：swipe from_x=0.5,from_y=0.8, to_x=0.5,to_y=0.2，duration_ms=300
  总结：下拉搜索 from_y=0.35，通知栏 from_y=0.0，上划抽屉 from_y=0.8。不要搞混！

## 长按使用场景
  - 需要弹出上下文菜单（复制/粘贴/删除/分享）
  - 桌面图标长按（卸载/快捷方式）
  - 选择列表中的单条消息/文件

## 禁止点击的悬浮控件
  屏幕边缘可能有一个圆形 PonyChat 悬浮头像（中断按钮），绝对不要点击它！

坐标规则：全部使用 0.0~1.0 归一化小数，左上角=(0,0)，右下角=(1,1)。禁止像素值！

输出格式示例（七选一，JSON 可含可选 thought 字段）：
{"type":"tap","x":0.52,"y":0.35,"thought":"点击搜索按钮"}
{"type":"long_press","x":0.5,"y":0.4,"thought":"长按消息弹出菜单"}
{"type":"swipe","from_x":0.5,"from_y":0.8,"to_x":0.5,"to_y":0.2,"duration_ms":400}
{"type":"input_text","text":"要搜索的内容"}
{"type":"system","action":"home"}
{"type":"launch","app":"相册"}
{"type":"wait","ms":2000}
{"type":"none","reason":"原因"}
{"type":"failed","reason":"找不到目标输入框"}
"""


def _build_device_gesture_hint(device_model: str | None, os_version: str | None,
                               os_flavor: str | None, nav_mode: str | None) -> str:
    """
    根据设备信息动态生成厂商特定手势参考提示，注入 _AGENT_ACTION_SYSTEM。
    不同厂商的下拉搜索/通知区域/快捷设置入口存在差异，需要分别说明。
    """
    flavor_lower = (os_flavor or "").lower()
    nav_lower = (nav_mode or "").lower()

    lines = []

    # ── 厂商特有提示 ─────────────────────────────────────────────────────────
    if "miui" in flavor_lower or "xiaomi" in flavor_lower or "hyperos" in flavor_lower:
        lines.append(
            "设备提示（小米/MIUI/HyperOS）：\n"
            "  - 下拉搜索：从屏幕中间(from_y=0.35)向下滑动；\n"
            "  - 通知中心：从屏幕顶部(from_y=0.0)向下滑；\n"
            "  - 控制中心：某些版本需从右上角斜向下滑；\n"
            "  - 应用抽屉（HyperOS）：上滑从 from_y=0.8；\n"
            "  - 锁屏：音量键+电源键截图，截图保存在相册。"
        )
    elif "emui" in flavor_lower or "harmonyos" in flavor_lower or "huawei" in flavor_lower:
        lines.append(
            "设备提示（华为/EMUI/HarmonyOS）：\n"
            "  - 下拉搜索：从桌面顶部或中部(from_y=0.3)向下滑；\n"
            "  - 通知+控制中心：从屏幕顶部分两侧下拉（右侧为快捷开关）；\n"
            "  - 应用抽屉：部分机型没有抽屉，默认桌面分屏；\n"
            "  - 截图：电源键+音量减，或手握边缘滑入。"
        )
    elif "oneui" in flavor_lower or "samsung" in flavor_lower:
        lines.append(
            "设备提示（三星/OneUI）：\n"
            "  - 下拉搜索：Bixby 搜索在桌面最左页，全局搜索从 from_y=0.3 下拉；\n"
            "  - 通知栏：从屏幕顶部下拉；快捷设置需两次下拉或双指下拉；\n"
            "  - 应用抽屉：从桌面上划(from_y=0.8)；\n"
            "  - 截图：侧边键+音量减，或手掌滑动（需开启）。"
        )
    elif "coloros" in flavor_lower or "oppo" in flavor_lower or "realme" in flavor_lower:
        lines.append(
            "设备提示（OPPO/ColorOS/Realme）：\n"
            "  - 全局搜索：桌面下拉(from_y=0.35)；\n"
            "  - 通知栏：顶部下拉；\n"
            "  - 应用抽屉：ColorOS 默认无抽屉，所有 App 在桌面；\n"
            "  - 截图：音量减+电源键。"
        )
    elif "originos" in flavor_lower or "vivo" in flavor_lower or "iqoo" in flavor_lower:
        lines.append(
            "设备提示（vivo/OriginOS/iQOO）：\n"
            "  - 全局搜索：桌面下拉(from_y=0.35)；\n"
            "  - 通知栏：顶部下拉；\n"
            "  - 应用抽屉（OriginOS）：桌面上划可能进入原子岛/抽屉；\n"
            "  - 截图：音量减+电源键，或三指下滑（需开启）。"
        )

    # ── 导航方式提示 ─────────────────────────────────────────────────────────
    if "gesture" in nav_lower or "full_screen" in nav_lower or "gestures" in nav_lower:
        lines.append(
            "导航方式（全面屏手势）：\n"
            "  - 返回：从左/右边缘向内滑；system back 仍可用；\n"
            "  - 主页：从底部上滑到中间停顿；system home 仍可用；\n"
            "  - 多任务：从底部上滑并保持；system recents 仍可用。"
        )
    elif "3_button" in nav_lower or "three_button" in nav_lower or "nav_bar" in nav_lower:
        lines.append(
            "导航方式（三键导航栏）：\n"
            "  - 底部有返回/主页/多任务三个虚拟按钮；\n"
            "  - 使用 system back/home/recents 操作即可，无需手势。"
        )

    if not lines:
        return ""
    return "\n\n".join(lines)


async def _decide_agent_action(image_base64: str, user_task: str, chat_history: list,
                               step_history: list[str] | None = None, username: str = "",
                               client_context: "ClientContext | None" = None,
                               current_plan_step: str = "", plan_total: int = 0,
                               plan_step_index: int = 0,
                               model_cfg: dict | None = None,
                               ui_elements: list[str] | None = None) -> dict:
    """
    调用活跃模型，根据截图和任务描述快速决定下一步触控操作。
    返回 action dict（如 {"type":"tap","x":0.5,"y":0.3}），失败返回 {"type":"none"}。
    """
    try:
        content: list | str
        history_suffix = ""
        input_fail_count = 0
        if step_history:
            history_suffix = "\n已执行操作记录：" + "；".join(step_history)
            input_fail_count = sum(1 for step in step_history if "INPUT(" in step and "-FAIL" in step)
        if input_fail_count >= 2:
            history_suffix += (
                f"\n额外提示：之前输入已经连续失败 {input_fail_count} 次。"
                "现在不要继续盲目重复 input_text；应优先点击顶部搜索框重新聚焦，"
                "若任务目标是打开名称明确的 App，也可以直接 launch 作为兜底。"
            )
        if current_plan_step:
            # Plan-and-Execute 模式：保留用户原始目标，避免模型只盯着步骤描述而忽视任务是否已完成
            step_label = f"（整体计划第 {plan_step_index + 1}/{plan_total} 步）" if plan_total > 0 else ""
            user_goal = f"用户目标：{user_task}\n" if user_task else ""
            task_prompt = f"{user_goal}当前步骤{step_label}：{current_plan_step}{history_suffix}"
        else:
            task_prompt = f"任务：{user_task}{history_suffix}" if user_task else f"根据截图决定下一步操作{history_suffix}"
        # 无障碍树元素提示（精准坐标辅助）
        elements_note = ""
        if ui_elements:
            elements_note = "\n\n界面可交互元素（格式 [标签](归一化x,归一化y)）：\n" + "  ".join(ui_elements[:20])

        if image_base64:
            image_data_url = f"data:image/jpeg;base64,{image_base64}"
            content = [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": task_prompt + elements_note},
            ]
        else:
            content = task_prompt + elements_note

        # 动态注入设备手势提示
        device_hint = ""
        if client_context:
            device_hint = "\n\n" + _build_device_gesture_hint(
                client_context.device_model,
                client_context.os_version,
                client_context.os_flavor,
                client_context.nav_mode,
            )
        system_prompt = _AGENT_ACTION_SYSTEM + device_hint

        _model = model_cfg or _MINI_MODEL
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        messages = _companion_inject_no_think(messages, _model)
        _eff_model_name = _companion_effective_model_name(_model)
        payload = {
            "model": _eff_model_name,
            "messages": messages,
            "stream": False,
        }
        apply_llm_task_payload_config(payload, "companion_agent_action")
        reasoning_policy = _companion_reasoning_policy("companion_agent_action", _model, _eff_model_name)
        action_timeout = llm_task_float("companion_agent_action", "timeout_seconds", 8.0) or 8.0

        # 提取 JSON：用括号计数法处理嵌套/多余文字，比简单正则更健壮
        def _extract_json_obj(text: str) -> str | None:
            start = text.find('{')
            if start == -1:
                return None
            depth = 0
            for i, ch in enumerate(text[start:]):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:start + i + 1]
            return None

        try:
            _ar = await call_llm_payload(
                payload,
                _model,
                task="companion",
                timeout=action_timeout,
                reasoning_policy=reasoning_policy,
                record_usage="companion",
                usage_meter_username=username or None,
            )
        except httpx.HTTPStatusError as e:
            _txt = (e.response.text[:300] if e.response is not None else "") or ""
            _code = e.response.status_code if e.response is not None else 0
            logger.warning(f"[AgentAction] 决策 API 错误 {_code}: {_txt}")
            _write_companion_sub_log("agent", username or "unknown", payload, _txt, error=f"http_{_code}")
            return {"type": "none", "reason": f"决策 API {_code}"}
        data = _ar.raw_response
        raw = (_ar.text or "").strip()

        json_str = _extract_json_obj(raw)
        if not json_str:
            # 模型把 token 全用于推理未输出 JSON → 重试一次，强制要求只输出 JSON
            logger.warning(f"[AgentAction] 未找到 JSON (第1次)，发起重试")
            retry_messages = messages + [
                {"role": "assistant", "content": raw[:200]},  # 截断避免超长
                {"role": "user", "content": "你没有输出 JSON。请直接输出一个 JSON 对象，不要任何文字说明。"},
            ]
            retry_payload = {**payload, "messages": retry_messages}
            apply_llm_task_payload_config(retry_payload, "companion_agent_action")
            try:
                _retry_r = await call_llm_payload(
                    retry_payload,
                    _model,
                    task="companion",
                    timeout=action_timeout,
                    reasoning_policy=reasoning_policy,
                    record_usage="companion",
                    usage_meter_username=username or None,
                )
                retry_raw = (_retry_r.text or "").strip()
                json_str = _extract_json_obj(retry_raw)
                if json_str:
                    raw = retry_raw
                    logger.info(f"[AgentAction] 重试成功，提取到 JSON")
            except Exception as retry_err:
                logger.warning(f"[AgentAction] 重试请求失败: {retry_err}")

        if not json_str:
            logger.warning(f"[AgentAction] 未找到 JSON, raw={raw!r}")
            _write_companion_sub_log("agent", username or "unknown", payload, raw, error="no_json")
            return {"type": "none", "reason": "决策失败，模型未返回 JSON"}
        try:
            action = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(f"[AgentAction] JSON 解析失败, json_str={json_str!r}, raw={raw!r}")
            _write_companion_sub_log("agent", username or "unknown", payload, raw, error="json_decode_error")
            return {"type": "none", "reason": "决策失败，JSON 格式错误"}
        act_type = action.get("type")
        if act_type not in ("tap", "long_press", "swipe", "input_text", "none", "system", "launch", "failed"):
            logger.warning(f"[AgentAction] 未知操作类型: {act_type!r}, raw={raw!r}")
            _write_companion_sub_log("agent", username or "unknown", payload, raw, error=f"unknown_type_{act_type}")
            return {"type": "none", "reason": f"未知操作类型: {act_type}"}
        # 坐标范围校验：若模型返回了像素值（>1），记录警告但仍透传——客户端会自动处理
        if act_type == "tap":
            x, y = action.get("x", 0), action.get("y", 0)
            if x > 1 or y > 1:
                logger.warning(f"[AgentAction] 坐标超出归一化范围 x={x}, y={y}，疑似像素值，已透传由客户端处理")
        elif act_type == "swipe":
            coords = [action.get(k, 0) for k in ("from_x", "from_y", "to_x", "to_y")]
            if any(c > 1 for c in coords):
                logger.warning(f"[AgentAction] swipe 坐标超出归一化范围 {coords}，疑似像素值，已透传由客户端处理")
        # 格式化 result 摘要（方便在日志文件名/元数据里快速看出执行了什么）
        if act_type == "tap":
            result_summary = f"TAP x={action.get('x')} y={action.get('y')}"
        elif act_type == "long_press":
            result_summary = f"LONG_PRESS x={action.get('x')} y={action.get('y')}"
        elif act_type == "swipe":
            result_summary = (f"SWIPE ({action.get('from_x')},{action.get('from_y')})"
                              f"→({action.get('to_x')},{action.get('to_y')})")
        elif act_type == "input_text":
            result_summary = f"INPUT_TEXT 「{str(action.get('text',''))[:20]}」"
        elif act_type == "system":
            result_summary = f"SYSTEM {action.get('action','')}"
        elif act_type == "launch":
            result_summary = f"LAUNCH {action.get('app','')}"
        elif act_type == "failed":
            result_summary = f"FAILED reason={action.get('reason','')}"
        else:
            result_summary = f"NONE reason={action.get('reason','')}"
        _write_companion_sub_log("agent", username or "unknown", payload, raw, result=result_summary)
        return action
    except Exception as e:
        logger.warning(f"[AgentAction] 操作决策异常: {type(e).__name__}: {e!r}")
    return {"type": "none", "reason": "决策失败，跳过操作"}


# ── Plan-and-Execute：任务规划 ────────────────────────────────────────────────

_AGENT_PLAN_SYSTEM = """\
你是手机操作规划助手。根据用户的任务描述和当前截图，判断是否需要操作手机并制定计划。
只输出 JSON，不要任何解释文字。

## 判断意图类型
1. 停止指令：用户说停下来、退出、停止、算了、不用了、取消吧、好了不用做了等终止操作的语义
   -> 返回：{"stop": true, "plan": [], "reaction": "好的，我停下来了"}

2. 纯对话（不需要操作手机）：包括但不限于：
   - 打招呼、闲聊、感谢、确认（好的/知道了）、表达情绪
   - 询问当前时间、日期：上下文已含 time_iso，无需打开任何 App
   - 询问当前所在地的天气/温度/天气预报：上下文已含 weather_desc/temperature，无需打开天气 App
   -> 返回：{"chat": true, "plan": [], "reaction": "用角色口吻简短自然回应，不超过25字"}

3. 需要操作手机：要求打开/搜索/发送/找到/设置/拍照等明确操作，
   或询问其他城市/地点的天气（上下文里没有该地信息），
   或需要在地图/导航 App 里实际操作的任务
   -> 返回：{"plan": ["步骤1", ...], "reaction": "角色口吻简短说明要做什么"}

## 任务规划规则（仅适用于3）
- 步骤数量：1~6步，简单任务1~2步即可
- 打开 App：第一步永远是 launch，格式写 launch 天气、launch 相册
- 如果截图已显示在目标界面，跳过导航步骤，直接从操作步骤开始
- reaction：不超过20字，用角色口吻简洁告知

示例（打招呼）：
{"chat": true, "plan": [], "reaction": "Jason！有什么需要帮你的吗~"}
示例（问现在几点）：
{"chat": true, "plan": [], "reaction": "上下文已有时间，直接回答即可"}
示例（问当前天气）：
{"chat": true, "plan": [], "reaction": "上下文已有天气，直接回答即可"}
示例（问上海天气 / 其他城市）：
{"plan": ["launch 天气，搜索上海天气"], "reaction": "好，我帮你查上海天气~"}
示例（停止）：
{"stop": true, "plan": [], "reaction": "好的，我停下来了"}
示例（发消息）：
{"plan": ["打开Pony应用", "找到张三的聊天界面", "在输入框输入你好并发送"], "reaction": "好，我帮你发消息给张三！"}
"""


async def _create_agent_plan(image_base64: str, task: str, username: str = "",
                              client_context: "ClientContext | None" = None,
                              model_cfg: dict | None = None) -> dict:
    """
    根据任务描述和当前截图，生成执行计划（步骤列表）。
    返回 {"plan": [...], "reaction": "..."}，失败时降级为单步计划。
    """
    try:
        content: list | str

        # 构建上下文摘要（时间/天气），让规划模型知道哪些信息无需打开 App
        ctx_parts = []
        if client_context:
            if client_context.time_iso:
                ctx_parts.append(f"当前时间：{client_context.time_iso}")
            weather_parts = []
            if client_context.location_name:
                weather_parts.append(client_context.location_name)
            if client_context.weather_desc:
                weather_parts.append(client_context.weather_desc)
            if client_context.temperature:
                weather_parts.append(client_context.temperature)
            if weather_parts:
                ctx_parts.append(f"当前天气：{'，'.join(weather_parts)}")
        ctx_note = f"\n（上下文已知：{'；'.join(ctx_parts)}）" if ctx_parts else ""

        task_text = f"任务：{task}{ctx_note}"

        if image_base64:
            image_data_url = f"data:image/jpeg;base64,{image_base64}"
            content = [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": task_text},
            ]
        else:
            content = task_text

        device_hint = ""
        if client_context:
            device_hint = "\n\n" + _build_device_gesture_hint(
                client_context.device_model,
                client_context.os_version,
                client_context.os_flavor,
                client_context.nav_mode,
            )

        _model = model_cfg or _MINI_MODEL
        messages = [
            {"role": "system", "content": _AGENT_PLAN_SYSTEM + device_hint},
            {"role": "user", "content": content},
        ]
        messages = _companion_inject_no_think(messages, _model)
        _eff_model_name = _companion_effective_model_name(_model)
        payload = {
            "model": _eff_model_name,
            "messages": messages,
            "stream": False,
        }
        apply_llm_task_payload_config(payload, "companion_agent_plan")
        reasoning_policy = _companion_reasoning_policy("companion_agent_plan", _model, _eff_model_name)
        try:
            _pr = await call_llm_payload(
                payload,
                _model,
                task="companion",
                timeout=llm_task_float("companion_agent_plan", "timeout_seconds", 10.0) or 10.0,
                reasoning_policy=reasoning_policy,
                record_usage="companion",
                usage_meter_username=username or None,
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"[AgentPlan] 规划 API 错误 {e.response.status_code if e.response else 0}: {(e.response.text[:200] if e.response else '')!r}")
            return {"plan": [task], "reaction": "好，我来帮你做！"}
        data = _pr.raw_response
        raw = (_pr.text or "").strip()

        def _extract_json_obj(text: str) -> str | None:
            start = text.find('{')
            if start == -1:
                return None
            depth = 0
            for i, ch in enumerate(text[start:]):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:start + i + 1]
            return None

        json_str = _extract_json_obj(raw)
        if json_str:
            result = json.loads(json_str)
            # 停止信号：LLM 判断任务是"停止/取消"语义
            if result.get("stop"):
                reaction = result.get("reaction", "好的，我停下来了")
                logger.info(f"🛑 [AgentPlan] {username}: 检测到停止指令，不启动循环")
                return {"plan": [], "stop": True, "reaction": reaction}
            # 纯对话信号：LLM 判断用户只是聊天，不需要操作手机
            if result.get("chat"):
                reaction = result.get("reaction", "有什么需要帮你的吗~")
                logger.info(f"💬 [AgentPlan] {username}: 检测到纯对话，跳过任务执行，reaction={reaction!r}")
                # 写 ChatLogs（纯对话回应没有 agent_action 日志，在此补写）
                asyncio.get_event_loop().run_in_executor(
                    None,
                    _write_companion_sub_log,
                    "agent_chat", username, payload, raw, reaction, "", "",
                )
                return {"plan": [], "chat": True, "reaction": reaction}
            plan = result.get("plan", [])
            if isinstance(plan, list) and len(plan) > 0:
                clean_plan = [str(s).strip() for s in plan if str(s).strip()]
                if clean_plan:
                    logger.info(f"🗒️ [AgentPlan] {username}: {len(clean_plan)} 步 → {clean_plan}")
                    return {
                        "plan": clean_plan,
                        "reaction": result.get("reaction", "好，我来帮你！"),
                    }
    except Exception as e:
        logger.warning(f"[AgentPlan] 规划失败: {type(e).__name__}: {e}")
    return {"plan": [task], "reaction": "好，我来帮你！"}


@router.post("/api/companion/agent_plan")
async def agent_plan_endpoint(
    body: FrameRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """
    操作陪玩任务规划端点（Plan-and-Execute 第一阶段）：
    根据截图和任务描述，生成分步执行计划。
    返回: {"plan": ["步骤1", ...], "reaction": "角色口吻的规划说明"}
    """
    auth_username = await _verify(x_chat_auth)
    if not auth_username:
        return {"error": "unauthorized", "plan": [], "reaction": ""}

    task = body.user_text.strip()
    if not task:
        return {"error": "no_task", "plan": [], "reaction": "你想让我做什么呢？"}

    # UI 树可用时不把截图发给模型，规划留在 DeepSeek Flash。
    # 只有缺少结构化界面信息时才启用DeepSeek 视觉。
    plan_image = body.image_base64.strip() if not body.ui_elements else ""
    active_model = get_companion_model_for(
        has_image=bool(plan_image),
        high_difficulty=is_high_difficulty_task(task),
    )

    t0 = time.perf_counter()
    result = await _create_agent_plan(
        plan_image, task,
        username=body.username,
        client_context=body.client_context,
        model_cfg=active_model,
    )
    elapsed = time.perf_counter() - t0
    plan_type = "stop" if result.get("stop") else ("chat" if result.get("chat") else f"{len(result.get('plan', []))}步")
    logger.info(f"🤖 [AgentPlan] {body.username}: plan={result['plan']} | 类型={plan_type} 耗时={elapsed:.2f}s")
    return result


@router.post("/api/companion/agent_action")
async def agent_action_stream(
    body: FrameRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """
    操作陪玩流式端点：在聊天陪玩的基础上，额外让 AI 决定并下发触控操作指令。
    SSE 格式同 /api/companion/stream，done 事件额外附带 action 字段：
      data: {"done": true, "reaction": "...", "action": {"type": "tap", "x": 0.5, "y": 0.3}}
    """
    auth_username = await _verify(x_chat_auth)
    if not auth_username:
        async def _err():
            yield 'data: {"error":"unauthorized"}\n\n'
        return StreamingResponse(_err(), media_type="text/event-stream")

    char_row = await _load_character_row(body.username, body.character_id)
    if not char_row:
        async def _err2():
            yield 'data: {"error":"character_not_found"}\n\n'
        return StreamingResponse(_err2(), media_type="text/event-stream")

    char_name = char_row["name"]
    persona = await _get_effective_persona(char_row)

    _memory_block = ""
    _layers: dict = {}
    try:
        _layers = await recall_memories_layered(username=body.username, character_id=body.character_id)
        _memory_block = format_layered_memories_for_prompt(**_layers)
    except Exception:
        pass

    persona_with_memory = persona
    if _memory_block:
        persona_with_memory = f"{persona}\n\n{_memory_block}" if persona else _memory_block
    persona_with_memory = f"{persona_with_memory}\n\n{_COMPANION_ROLEPLAY_ANCHOR}" if persona_with_memory else _COMPANION_ROLEPLAY_ANCHOR
    persona_with_memory = apply_personality_style(persona_with_memory, body.personality_style)
    _pref_override = _build_preference_override(_layers.get("c_entries", []))
    if _pref_override:
        persona_with_memory = f"{persona_with_memory}\n\n{_pref_override}"

    sess_key = _session_key(body.username, body.character_id)
    session = _get_or_create_session(sess_key)

    _env_ctx_text = ""
    if body.client_context:
        _env_ctx_text = format_client_context(body.client_context)
    _env_block = f"{_env_ctx_text}\n\n" if _env_ctx_text else ""

    has_text = bool(body.user_text.strip())
    has_image = bool(body.image_base64.strip())
    is_proactive = bool(body.proactive_hint.strip()) and not has_text

    # 操作陪玩的 system prompt：同时告知 AI 它可能会执行操作
    _step_hist_note = ""
    if body.agent_step_history:
        _step_hist_note = (
            "本次任务已执行的操作记录：" + "；".join(body.agent_step_history) + "\n"
            "如果记录中已有操作，你的回复应描述操作后的结果或当前画面状态，"
            "不要再说我要点击XXX，那一步已经做过了。\n"
        )
    agent_task_prefix = (
        "你不仅是陪伴用户的角色，同时也在帮用户操作手机。"
        "你可以观察屏幕、决定要点击或滑动哪里，但你的语言回复仍要保持角色口吻，"
        "不要暴露『我在分析屏幕坐标』等技术细节。\n"
    ) + _step_hist_note

    if is_proactive:
        # ── 主动发言（进入陪玩时的问候 / followup）：纯文字，无截图，不触发操作 ─
        limit = max(10, min(body.max_chars, 60))
        hint = body.proactive_hint.strip()
        if hint == "greeting":
            task_instruction = (
                f"用户刚刚开启了操作陪玩，这是本次陪玩的第一句话。"
                f"用你的角色口吻自然地打个招呼，不超过{limit}字，不加任何前缀或引号。"
            )
        else:
            task_instruction = (
                f"用户没有回应你，你趁空档主动再说一句话延续聊天。"
                f"不能重复刚才说过的内容；口语化自然，不超过{limit}字，不加任何前缀或引号。"
            )
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + task_instruction
        if has_image:
            image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
            current_user_msg = {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": "(陪玩开始)"},
                ],
            }
        else:
            current_user_msg = {"role": "user", "content": "(陪玩开始)"}
        token_budget = max(60, limit * 3)
        is_text_mode = True

    elif has_text and has_image:
        limit = max(10, min(body.max_chars, 100))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + agent_task_prefix + (
            f"用户发来了截图和文字。请结合截图理解上下文，用角色口吻自然回应，"
            f"不超过{limit}字，口语化，不加任何前缀或引号。"
        )
        image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": body.user_text.strip()},
            ],
        }
        token_budget = max(60, limit * 3)
        is_text_mode = True

    elif has_text:
        limit = max(10, min(body.max_chars, 100))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + agent_task_prefix + (
            f"用户直接跟你说话了。请用角色口吻自然回应，不超过{limit}字，口语化，不加任何前缀或引号。"
        )
        current_user_msg = {"role": "user", "content": body.user_text.strip()}
        token_budget = max(60, limit * 3)
        is_text_mode = True

    elif has_image:
        # 纯截图：AI 观察画面后发表评论并决定操作
        limit = max(10, min(body.max_chars, 50))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + agent_task_prefix + (
            "观察截图，用角色口吻发表一句简短评论（同时你会决定要不要帮用户点点按钮）。"
            f"不超过{limit}字，口语化，不加前缀或引号。"
        )
        image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": "请基于图片回应"},
            ],
        }
        token_budget = max(40, limit * 3)
        is_text_mode = False

    else:
        # 既无截图也无文字（不应出现，保底返回空响应）
        async def _empty():
            yield f"data: {json.dumps({'done': True, 'reaction': '', 'action': {'type': 'none'}}, ensure_ascii=False)}\n\n"
        return StreamingResponse(
            _empty(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    # 角色回应若包含截图仍需视觉模型；实际操作决策优先只用 UI 树。
    active_model = get_companion_model_for(
        has_image=has_image,
        high_difficulty=is_high_difficulty_task(body.user_text),
    )
    action_model = get_companion_model_for(
        has_image=bool(has_image and not body.ui_elements),
        high_difficulty=is_high_difficulty_task(body.user_text),
    )
    next_frame = session["frame_count"] + (0 if is_text_mode else 1)

    async def _generate():
        t_gen_start = time.perf_counter()
        full_content = ""

        # ── 1. 先决策 action（避免 companion reaction 与 action 说一套做一套）──────
        if is_proactive or not has_image:
            action: dict = {"type": "none"}
            t_decide_elapsed = 0.0
        else:
            user_task = body.user_text.strip() or "用户没有明确说要操作手机，请返回 none。"
            action_image = body.image_base64 if not body.ui_elements else ""
            if action_image and not action_model.get("supports_vision", False):
                yield f"data: {json.dumps({'error': 'vision_not_supported'}, ensure_ascii=False)}\n\n"
                return
            t_decide = time.perf_counter()
            action = await _decide_agent_action(
                action_image, user_task, session["history"],
                step_history=body.agent_step_history or None,
                username=body.username,
                client_context=body.client_context,
                current_plan_step=body.current_plan_step,
                plan_total=body.plan_total,
                plan_step_index=body.plan_step_index,
                model_cfg=action_model,
                ui_elements=body.ui_elements or None,
            )
            t_decide_elapsed = time.perf_counter() - t_decide

        # ── skip_reaction 模式：只返回操作指令，不生成角色回复 ────────────────────
        if body.skip_reaction:
            t_total = time.perf_counter() - t_gen_start
            logger.info(
                f"🤖 [AgentAction/skip] {auth_username}/{char_name}: "
                f"[{action.get('type', 'none')}] 总计={t_total:.2f}s"
            )
            yield f"data: {json.dumps({'done': True, 'reaction': '', 'action': action}, ensure_ascii=False)}\n\n"
            return

        # ── 2. 根据 action 生成一句"行动提示"注入 companion system prompt ──────────
        act_type = action.get("type", "none")
        _sys_map = {"home": "返回桌面", "back": "返回上一页", "recents": "查看最近任务"}
        if act_type == "tap":
            action_note = "你正在点击屏幕上的一个元素。"
        elif act_type == "long_press":
            action_note = "你正在长按屏幕上的一个元素。"
        elif act_type == "swipe":
            action_note = "你正在滑动屏幕。"
        elif act_type == "input_text":
            action_note = f'你正在向输入框输入文字：{action.get("text","")[:15]}。'
        elif act_type == "system":
            action_note = f'你正在执行系统操作：{_sys_map.get(action.get("action",""), action.get("action",""))}。'
        elif act_type == "launch":
            action_note = f'你正在直接启动 {action.get("app","")} App。'
        elif act_type == "failed":
            action_note = f'当前步骤无法完成：{action.get("reason","未知原因")}。'
        else:
            action_note = ""

        final_system_prompt = system_prompt
        if action_note:
            final_system_prompt = (
                system_prompt
                + f"\n\n你本次将要执行的操作：{action_note}"
                "请在回复中自然地描述你正在做的事，保持角色口吻，不要说我要做...而是说我正在...或我已经...。"
            )

        # ── 3. 构建并发送 companion 流式请求 ──────────────────────────────────────
        msgs: List[dict] = [{"role": "system", "content": final_system_prompt}]
        msgs.extend(session["history"])
        msgs.append(current_user_msg)
        msgs = _companion_inject_no_think(msgs, active_model)

        _eff_model_name = _companion_effective_model_name(active_model)
        payload = {
            "model": _eff_model_name,
            "messages": msgs,
            "stream": True,
        }
        apply_llm_task_payload_config(payload, "companion_agent_action")
        reasoning_policy = _companion_reasoning_policy("companion_agent_action", active_model, _eff_model_name)
        action_timeout = llm_task_float("companion_agent_action", "timeout_seconds", float(GENERATE_TIMEOUT_SEC)) or float(GENERATE_TIMEOUT_SEC)
        _agent_stream_dbg = {
            k: v
            for k, v in (
                ("temperature", payload.get("temperature")),
                (
                    "max_tokens",
                    payload.get("max_completion_tokens") or payload.get("max_tokens"),
                ),
            )
            if v is not None
        }

        t_stream = time.perf_counter()
        stream_usage = None
        try:
            async with httpx.AsyncClient(timeout=action_timeout) as client:
                try:
                    async for delta in call_llm_stream_payload(
                        payload,
                        active_model,
                        task="companion",
                        httpx_client=client,
                        timeout=action_timeout,
                        reasoning_policy=reasoning_policy,
                        chat_debug_request={
                            "username": auth_username or body.username,
                            "character_id": body.character_id,
                            "mode": "companion_agent",
                            "model_name": _eff_model_name,
                            "stage": "REQUEST",
                            "params": _agent_stream_dbg or None,
                        },
                    ):
                        if delta:
                            full_content += delta
                            yield f"data: {json.dumps({'d': delta}, ensure_ascii=False)}\n\n"
                except httpx.HTTPStatusError as e:
                    body_bytes = (e.response.text[:200] if e.response is not None else "") or ""
                    logger.warning(f"[AgentAction] 模型调用失败 {e.response.status_code if e.response else 0}: {body_bytes}")
                    yield f'data: {json.dumps({"error": "model_error"}, ensure_ascii=False)}\n\n'
                    return
        except Exception as e:
            logger.warning(f"[AgentAction] 流式异常: {type(e).__name__}: {e!r}")
            yield f'data: {json.dumps({"error": "stream_error"}, ensure_ascii=False)}\n\n'
            return
        t_stream_elapsed = time.perf_counter() - t_stream

        # 写入 session 历史
        placeholder = _append_to_session(
            sess_key, next_frame, full_content,
            user_text=body.user_text.strip() if (is_text_mode and not is_proactive) else "",
            with_image=has_image,
            skip_user=(is_proactive and not has_image),
        )
        if placeholder and body.image_base64:
            asyncio.create_task(
                _describe_and_patch_history(sess_key, body.image_base64, placeholder, username=body.username)
            )

        # 格式化操作描述，方便日志直观排查
        act_type = action.get("type", "none")
        if act_type == "tap":
            act_desc = f"TAP  x={action.get('x'):.3f}  y={action.get('y'):.3f}"
        elif act_type == "swipe":
            act_desc = (
                f"SWIPE  ({action.get('from_x'):.3f},{action.get('from_y'):.3f})"
                f" → ({action.get('to_x'):.3f},{action.get('to_y'):.3f})"
                f"  {action.get('duration_ms',300)}ms"
            )
        elif act_type == "long_press":
            act_desc = f"LONG_PRESS  x={action.get('x'):.3f}  y={action.get('y'):.3f}"
        elif act_type == "input_text":
            act_desc = f"INPUT_TEXT  text={action.get('text','')[:20]!r}"
        elif act_type == "system":
            act_desc = f"SYSTEM  action={action.get('action','')!r}"
        elif act_type == "launch":
            act_desc = f"LAUNCH  app={action.get('app','')!r}"
        else:
            act_desc = f"NONE  reason={action.get('reason','')!r}"
        t_total = time.perf_counter() - t_gen_start
        logger.info(
            f"🤖 [AgentAction] {auth_username}/{char_name}: [{act_desc}]  reaction={full_content!r} "
            f"| 决策={t_decide_elapsed:.2f}s 流式={t_stream_elapsed:.2f}s 总计={t_total:.2f}s"
        )
        _write_companion_log(body.username, char_name, payload, "", reaction=full_content)

        # 陪玩：流式回复每次成功计入 companion 用量 + 用户每日次数
        try:
            if stream_usage:
                inp, out = extract_usage_from_response(stream_usage)
            else:
                inp = estimate_tokens(payload.get("messages") or msgs)
                out = estimate_output_tokens(full_content)
            await get_users_dao().increment_companion_usage(
                auth_username, inp, out, llm_api_calls=1,
            )
            await get_membership_dao().increment_by(auth_username, 1)
        except Exception:
            pass

        yield f"data: {json.dumps({'done': True, 'reaction': full_content, 'action': action}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
