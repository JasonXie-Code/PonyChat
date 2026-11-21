# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
from typing import Any

from schemas import AgentDecision, AgentReply, ChatMessage, CharacterProfile, WorkingState
from tools import (
    describe_pose_image_prompt_tool,
    export_conversation_document_tool,
    read_summaries_tool,
    search_memory_fragments_tool,
    select_character,
    update_working_state_tool,
)


def goose_command() -> str:
    return shutil.which("goose") or ""


class PonyChatGooseStyleAgent:
    def __init__(self, username: str = "System", remote_url: str = "", refresh_roles: bool = False) -> None:
        self.username = username
        self.remote_url = remote_url
        self.refresh_roles = refresh_roles

    def run_turn(
        self,
        character_id: str = "",
        character_index: int = 0,
        messages: list[dict[str, Any]] | None = None,
        latest_user_input: str = "",
        memory_fragments: list[str] | None = None,
        summaries: dict[str, Any] | None = None,
        working_state: dict[str, Any] | None = None,
    ) -> AgentReply:
        trace: list[AgentDecision] = []
        messages = messages or []
        chat_messages = [ChatMessage.from_dict(item) for item in messages if isinstance(item, dict)]
        latest = latest_user_input.strip() or _latest_user_text(chat_messages)

        character = select_character(
            character_id=character_id,
            character_index=character_index,
            username=self.username,
            refresh=self.refresh_roles,
            remote_url=self.remote_url,
        )
        trace.append(
            AgentDecision(
                step="load character setting",
                tool="load_system_characters/select_character",
                arguments={"character_id": character_id, "character_index": character_index},
                observation={
                    "id": character.id,
                    "name": character.name,
                    "persona_chars": len(character.persona_prompt),
                    "source": character.source,
                },
            )
        )

        memory_result = search_memory_fragments_tool(
            {
                "query": latest,
                "memory_fragments": memory_fragments or [],
                "limit": 5,
            }
        )
        trace.append(
            AgentDecision(
                step="search long memory fragments",
                tool="search_memory_fragments",
                arguments={"query": latest, "limit": 5},
                observation={"matches": memory_result.get("matches", []), "searched": memory_result.get("searched", 0)},
            )
        )

        summary_result = read_summaries_tool({"summaries": summaries or {}})
        trace.append(
            AgentDecision(
                step="read long-range summaries",
                tool="read_summaries",
                arguments={"summary_keys": list((summaries or {}).keys())},
                observation=summary_result,
            )
        )

        state_payload = update_working_state_tool(
            {
                "working_state": working_state or {},
                "latest_user_input": latest,
            }
        )
        state = WorkingState.from_dict(state_payload)
        trace.append(
            AgentDecision(
                step="update temporary working state",
                tool="update_working_state",
                arguments={"latest_user_input": latest},
                observation=state.to_dict(),
            )
        )

        warnings = []
        if not goose_command():
            warnings.append("goose_cli_not_found_using_local_mock")

        if state.intent == "create_document":
            document = export_conversation_document_tool({"messages": messages, "title": "PonyChat Conversation"})
            trace.append(
                AgentDecision(
                    step="create requested document",
                    tool="export_conversation_document",
                    arguments={"message_count": len(messages)},
                    observation={"message_count": document.get("message_count", 0)},
                )
            )
            text = "我先把我们的对话整理成文档草稿了，你可以继续告诉我要不要改标题或分段。"
            return AgentReply(
                character_id=character.id,
                character_name=character.name,
                mode="normal_chat_agent_mock",
                reply_units=[{"type": "text", "text": text}],
                decisions=trace,
                working_state=state,
                artifacts=document,
                warnings=warnings,
            )

        if state.intent == "create_image_prompt":
            image_prompt = describe_pose_image_prompt_tool(
                {
                    "character": character.to_dict(),
                    "latest_user_input": latest,
                    "pose_hint": latest,
                }
            )
            trace.append(
                AgentDecision(
                    step="create requested image prompt",
                    tool="describe_pose_image_prompt",
                    arguments={"latest_user_input": latest},
                    observation={"image_prompt_chars": len(str(image_prompt.get("image_prompt") or ""))},
                )
            )
            text = "我把这张图的姿势提示词先整理好了，等接入图片生成工具后就能直接交给绘图模型。"
            return AgentReply(
                character_id=character.id,
                character_name=character.name,
                mode="normal_chat_agent_mock",
                reply_units=[{"type": "text", "text": text}],
                decisions=trace,
                working_state=state,
                artifacts=image_prompt,
                warnings=warnings,
            )

        reply_text = _mock_character_reply(
            character=character,
            latest_user_input=latest,
            state=state,
            memory_matches=memory_result.get("matches", []),
            summaries=summary_result.get("summaries", {}),
        )
        trace.append(
            AgentDecision(
                step="compose final character message",
                tool="local_mock_reply_writer",
                arguments={"mode": "ordinary_chat"},
                observation={"reply_chars": len(reply_text)},
            )
        )
        return AgentReply(
            character_id=character.id,
            character_name=character.name,
            mode="normal_chat_agent_mock",
            reply_units=[{"type": "text", "text": reply_text}],
            decisions=trace,
            working_state=state,
            warnings=warnings,
        )


def _latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    return ""


def _mock_character_reply(
    character: CharacterProfile,
    latest_user_input: str,
    state: WorkingState,
    memory_matches: list[str],
    summaries: dict[str, str],
) -> str:
    data = character.raw_data
    name = character.name
    personality = str(data.get("profilePersonality") or data.get("personality") or "")
    intro = str(data.get("profileIntro") or data.get("bio") or data.get("description") or "")
    voice = f"{personality}\n{intro}".lower()

    has_memory = bool(memory_matches or summaries)
    memory_tail = ""
    if has_memory:
        memory_tail = "我也会把之前那些线索放在心里，不拿空话糊弄你。"

    if state.user_mood == "needs_support":
        if any(token in name or token in voice for token in ("碧琪", "pinkie", "活泼", "外向", "热情")):
            return f"那今天先别硬撑啦。你把最累的那一块丢给我，我负责接住它。{memory_tail}".strip()
        if any(token in name or token in voice for token in ("紫悦", "twilight", "理性", "智慧", "认真")):
            return f"先停一下，今天已经够累了。你不用马上把自己整理好，先告诉我是哪件事把你耗得最厉害。{memory_tail}".strip()
        if any(token in name or token in voice for token in ("柔柔", "fluttershy", "温柔", "内向", "害羞")):
            return f"嗯，我在这里。你可以慢慢说，不用说得很完整，我会认真听。{memory_tail}".strip()
        return f"我在。今天先不用逞强，挑一件最压着你的事说给我听就好。{memory_tail}".strip()

    if "?" in latest_user_input or "？" in latest_user_input:
        return "我会按自己的想法认真回答你。你刚刚问的这件事，我想先从最关键的地方说起。"

    if any(word in latest_user_input for word in ("早", "午安", "晚上好", "在吗", "醒了吗")):
        return "在呢，我刚好也想听听你现在怎么样。"

    if has_memory:
        return "我听到了，也会把之前那些线索一起放进现在这句话里看。你继续说，我跟得上。"

    return "嗯，我听着。你继续说，我会按我的方式陪你聊下去。"
