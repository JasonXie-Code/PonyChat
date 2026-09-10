from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
import tempfile
import time
from typing import Protocol

from .audit_log import PrivacyAuditLog, stable_private_reference
from .mobile_tools import MobileTools, ScreenElement
from .safety_policy import DeviceActionSafetyPolicy


class AgentStatus(Enum):
    COMPLETED = "completed"
    USER_ACTION_REQUIRED = "user_action_required"
    USER_STOPPED = "user_stopped"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class AgentDecision:
    kind: str
    summary: str
    target: dict[str, str] | None = None
    value: str = ""
    direction: str = ""
    verification: str = ""


@dataclass(frozen=True)
class AgentTurn:
    index: int
    observation_fingerprint: str
    environment: str
    decision: AgentDecision
    result: str


@dataclass(frozen=True)
class GeneralAgentResult:
    status: AgentStatus
    detail: str
    turns: tuple[AgentTurn, ...]


class DeviceAgentBrain(Protocol):
    def decide(
        self,
        *,
        goal: str,
        elements: list[ScreenElement],
        history: list[AgentTurn],
        learned_programs: list[dict],
        feedback: str,
        screenshot_path: str,
        high_difficulty: bool,
        installed_apps: str,
        environment: str,
    ) -> AgentDecision: ...


class SkillProgramMemory:
    """Stores successful semantic programs and recovery paths, never raw coordinates."""

    def __init__(self, path: str | Path | None = None) -> None:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PonyChat" / "Companion"
        self.path = Path(path) if path else root / "agent_skill_programs.json"

    def recall(
        self,
        goal: str,
        environment: str,
        *,
        task_family: str = "",
        limit: int = 5,
    ) -> list[dict]:
        key = self._goal_key(goal)
        family = task_family.strip()
        candidates = []
        for item in self._load():
            exact_goal = item.get("goal_key") == key
            same_family = bool(family) and item.get("task_family") == family
            if not exact_goal and not same_family:
                continue
            score = int(item.get("success_count", 0))
            if exact_goal:
                score += 20
            if same_family:
                score += 12
            if item.get("environment") == environment:
                score += 8
            candidates.append((score, item))
        return [item for _, item in sorted(candidates, key=lambda pair: pair[0], reverse=True)[:limit]]

    def record_success(
        self,
        goal: str,
        environment: str,
        turns: list[AgentTurn],
        *,
        task_family: str = "",
    ) -> None:
        programs = self._load()
        steps = [self._safe_step(turn) for turn in turns if turn.decision.kind not in {"finish", "blocked"}]
        signature = hashlib.sha256(
            json.dumps(steps, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        ).hexdigest()[:20]
        existing = next((
            item for item in programs
            if item.get("goal_key") == self._goal_key(goal)
            and item.get("environment") == environment
            and item.get("signature") == signature
        ), None)
        if existing is None:
            programs.append({
                "goal_key": self._goal_key(goal),
                "task_family": task_family.strip(),
                "environment": environment,
                "signature": signature,
                "steps": steps,
                "success_count": 1,
                "last_success_at": int(time.time()),
            })
        else:
            existing["success_count"] = int(existing.get("success_count", 0)) + 1
            existing["last_success_at"] = int(time.time())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 2, "programs": programs[-200:]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _goal_key(goal: str) -> str:
        normalized = "".join(character.lower() for character in goal if not character.isspace())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _safe_step(turn: AgentTurn) -> dict:
        decision = turn.decision
        payload = {
            "kind": decision.kind,
            "summary": decision.summary,
            "target": decision.target or {},
            "direction": decision.direction,
            "verification": decision.verification,
            "result": turn.result,
            "environment": turn.environment,
        }
        if decision.kind == "type_text":
            payload["value"] = "<task_text>"
        return payload

    def _load(self) -> list[dict]:
        try:
            return list(json.loads(self.path.read_text(encoding="utf-8")).get("programs", []))
        except (OSError, ValueError, TypeError):
            return []


class BlockerPolicy:
    """Only user authority, genuine ambiguity and safety confirmation may pause."""

    ACCOUNT_OR_PERMISSION = (
        "登录", "账号", "验证码", "权限", "授权", "password", "login", "captcha", "permission",
    )
    AMBIGUOUS_TARGET = (
        "目标不明确", "联系人不唯一", "多个候选", "无法唯一", "ambiguous", "multiple candidates",
    )
    SAFETY_CONFIRMATION = (
        "高风险", "用户明确确认", "提交前", "付款", "支付", "下单", "公开发布", "拨打",
    )

    @classmethod
    def may_pause(cls, reason: str) -> bool:
        normalized = reason.lower()
        return any(
            marker.lower() in normalized
            for marker in cls.ACCOUNT_OR_PERMISSION + cls.AMBIGUOUS_TARGET + cls.SAFETY_CONFIRMATION
        )


class GeneralDeviceAgent:
    """Observe-decide-act-verify-reflect loop for recoverable device tasks."""

    def __init__(
        self,
        tools: MobileTools,
        device: str,
        brain: DeviceAgentBrain,
        *,
        memory: SkillProgramMemory | None = None,
        timeout_seconds: float = 600.0,
        max_turns: int = 80,
        settle_seconds: float = 0.6,
        safety: DeviceActionSafetyPolicy | None = None,
        audit: PrivacyAuditLog | None = None,
    ) -> None:
        self.tools = tools
        self.device = device
        self.brain = brain
        self.memory = memory or SkillProgramMemory()
        self.timeout_seconds = timeout_seconds
        self.max_turns = max_turns
        self.settle_seconds = settle_seconds
        self.safety = safety or DeviceActionSafetyPolicy()
        self.audit = audit or PrivacyAuditLog()

    def run(self, goal: str, *, task_family: str = "") -> GeneralAgentResult:
        task_ref = stable_private_reference(goal)
        self.audit.record("agent_task_started", task_ref=task_ref, task_family=task_family)
        deadline = time.monotonic() + self.timeout_seconds
        history: list[AgentTurn] = []
        feedback = ""
        stagnant_turns = 0
        last_fingerprint = ""
        environment = "android:unknown"
        learned: list[dict] = []
        installed_apps = self._list_apps()
        observation_failures = 0
        while len(history) < self.max_turns and time.monotonic() < deadline:
            try:
                elements = self.tools.list_elements(self.device)
            except Exception as error:
                observation_failures += 1
                feedback = f"观察失败：{type(error).__name__}: {error}；请重新建立工具连接后继续"
                if observation_failures >= 3:
                    feedback += self._recover_observation_channel()
                    observation_failures = 0
                time.sleep(min(2.0, self.settle_seconds + stagnant_turns * 0.2))
                stagnant_turns += 1
                continue
            observation_failures = 0
            fingerprint = self._fingerprint(elements)
            current_environment = self._environment(elements)
            if not learned:
                environment = current_environment
                learned = self.memory.recall(
                    goal,
                    environment,
                    task_family=task_family,
                )
            stagnant_turns = stagnant_turns + 1 if fingerprint == last_fingerprint else 0
            last_fingerprint = fingerprint
            use_vision = not elements or stagnant_turns >= 2 or "失败" in feedback
            screenshot = self._capture_screenshot() if use_vision else ""
            decision = self.brain.decide(
                goal=goal,
                elements=elements,
                history=history,
                learned_programs=learned,
                feedback=feedback,
                screenshot_path=screenshot,
                high_difficulty=use_vision or len(history) >= 8,
                installed_apps=installed_apps,
                environment=current_environment,
            )
            if decision.kind == "finish":
                if not self._completion_is_grounded(decision, elements):
                    feedback = "模型尝试结束任务但完成证据无法在当前观察中定位，必须继续验证"
                    continue
                self.memory.record_success(
                    goal,
                    environment,
                    history,
                    task_family=task_family,
                )
                self.audit.record(
                    "agent_task_completed",
                    task_ref=task_ref,
                    turns=len(history),
                    environment=current_environment,
                )
                return GeneralAgentResult(AgentStatus.COMPLETED, decision.verification, tuple(history))
            if decision.kind == "blocked":
                reason = decision.summary or decision.verification
                if BlockerPolicy.may_pause(reason):
                    self.audit.record(
                        "agent_task_paused",
                        task_ref=task_ref,
                        turns=len(history),
                        reason=reason,
                    )
                    return GeneralAgentResult(AgentStatus.USER_ACTION_REQUIRED, reason, tuple(history))
                feedback = f"技术故障不能暂停：{reason}。请提出新的探索、恢复或替代路径"
                continue
            assessment = self.safety.assess(decision.kind, decision.target, elements)
            if assessment.requires_confirmation:
                self.audit.record(
                    "agent_task_paused",
                    task_ref=task_ref,
                    turns=len(history),
                    reason=assessment.reason,
                )
                return GeneralAgentResult(
                    AgentStatus.USER_ACTION_REQUIRED,
                    assessment.reason,
                    tuple(history),
                )
            result = self._execute(decision, elements)
            history.append(AgentTurn(
                len(history) + 1,
                fingerprint,
                current_environment,
                decision,
                result,
            ))
            self.audit.record(
                "agent_action",
                task_ref=task_ref,
                turn=len(history),
                kind=decision.kind,
                environment=current_environment,
                target_identifier=(decision.target or {}).get("identifier", ""),
                target_type=(decision.target or {}).get("type", ""),
                result="failed" if "失败" in result or "没有找到" in result else "observed",
            )
            feedback = result
            if self.settle_seconds:
                time.sleep(self.settle_seconds)
        self.audit.record(
            "agent_task_timeout",
            task_ref=task_ref,
            turns=len(history),
            environment=environment,
        )
        return GeneralAgentResult(
            AgentStatus.TIMEOUT,
            "自主恢复窗口已用尽，已保留完整轨迹供守护进程从最后安全状态续办",
            tuple(history),
        )

    @classmethod
    def _completion_is_grounded(
        cls,
        decision: AgentDecision,
        elements: list[ScreenElement],
    ) -> bool:
        evidence = decision.verification.strip()
        if not evidence:
            return False
        if decision.target:
            return not isinstance(cls._resolve_target(elements, decision.target), str)
        visible = {
            value.strip()
            for element in elements
            for value in element.strings
            if len(value.strip()) >= 2
        }
        return any(value in evidence or evidence in value for value in visible)

    def _execute(self, decision: AgentDecision, elements: list[ScreenElement]) -> str:
        try:
            if decision.kind == "launch_app":
                return self.tools.launch_app(self.device, decision.value)
            if decision.kind == "open_url":
                return self.tools.open_url(self.device, decision.value)
            if decision.kind == "press_button":
                return self.tools.press_button(self.device, decision.value)
            if decision.kind == "swipe":
                return self.tools.swipe(self.device, decision.direction or "UP")
            if decision.kind == "wait":
                time.sleep(max(0.1, min(float(decision.value or 1), 10.0)))
                return "等待后将重新观察"
            target = self._resolve_target(elements, decision.target or {})
            if isinstance(target, str):
                return target
            if decision.kind == "click":
                return self.tools.click(self.device, *target.center)
            if decision.kind == "long_press":
                return self.tools.long_press(self.device, *target.center)
            if decision.kind == "type_text":
                self.tools.click(self.device, *target.center)
                self.tools.clear_text(self.device)
                return self.tools.type_text(self.device, decision.value, submit=False)
            return f"未知动作 {decision.kind}，请重新规划"
        except Exception as error:
            return f"动作失败：{type(error).__name__}: {error}；重新观察并选择恢复路径"

    @staticmethod
    def _resolve_target(elements: list[ScreenElement], selector: dict[str, str]) -> ScreenElement | str:
        if not selector:
            return "动作缺少语义目标，不能盲点"
        candidates = list(elements)
        identifier = selector.get("identifier", "").strip()
        text = selector.get("text", "").strip()
        kind = selector.get("type", "").strip()
        if identifier:
            candidates = [item for item in candidates if item.identifier == identifier]
        if kind:
            candidates = [item for item in candidates if kind in item.type]
        if text:
            exact = [item for item in candidates if text in item.strings]
            candidates = exact or [item for item in candidates if any(text in value for value in item.strings)]
        if not candidates:
            return f"没有找到目标 {selector}，组件可能变化；请探索替代语义"
        if len(candidates) > 1:
            return f"目标 {selector} 匹配 {len(candidates)} 个组件；请补充父级、ID 或其他语义后重试"
        return candidates[0]

    def _capture_screenshot(self) -> str:
        path = str(Path(tempfile.gettempdir()) / f"ponychat-agent-{os.getpid()}.png")
        try:
            self.tools.save_screenshot(self.device, path)
            return path if Path(path).is_file() else ""
        except Exception:
            return ""

    def _list_apps(self) -> str:
        try:
            return str(self.tools.list_apps(self.device))[:20_000]
        except Exception as error:
            return f"应用列表不可用：{type(error).__name__}"

    def _recover_observation_channel(self) -> str:
        try:
            result = self.tools.press_button(self.device, "HOME")
            return f"；已回到 HOME 重建观察通道：{result}"
        except Exception as error:
            return f"；HOME 恢复也失败：{type(error).__name__}: {error}"

    @staticmethod
    def _environment(elements: list[ScreenElement]) -> str:
        packages = sorted({
            item.identifier.split(":id/", 1)[0]
            for item in elements
            if ":id/" in item.identifier
        })
        return "android:" + (",".join(packages[:6]) if packages else "semantic-only")

    @staticmethod
    def _fingerprint(elements: list[ScreenElement]) -> str:
        payload = [
            (item.type, item.identifier, item.strings)
            for item in elements
        ]
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        ).hexdigest()
