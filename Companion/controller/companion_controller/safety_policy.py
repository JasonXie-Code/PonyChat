from __future__ import annotations

from dataclasses import dataclass

from .mobile_tools import ScreenElement


@dataclass(frozen=True)
class SafetyAssessment:
    requires_confirmation: bool
    reason: str = ""


class DeviceActionSafetyPolicy:
    """Stops irreversible or identity-bearing actions at the final UI step."""

    FINAL_CONFIRMATION_MARKERS = (
        "立即支付", "确认支付", "付款", "支付", "提交订单", "确认下单", "立即购买",
        "转账", "发红包", "充值", "开通会员", "自动续费", "订阅",
        "公开发布", "确认发布", "发表", "发帖", "发布动态",
        "永久删除", "确认删除", "清空全部", "注销账号", "恢复出厂", "格式化",
        "拨打电话", "立即拨打", "呼叫",
        "允许访问", "始终允许", "授予权限", "同意授权",
    )
    SENSITIVE_FIELD_MARKERS = (
        "password", "passwd", "payment_password", "验证码", "支付密码", "银行卡",
        "身份证", "cvv", "security_code",
    )

    def assess(
        self,
        decision_kind: str,
        selector: dict[str, str] | None,
        elements: list[ScreenElement],
    ) -> SafetyAssessment:
        if decision_kind == "type_text":
            semantic = self._semantic_text(selector, elements).lower()
            if any(marker.lower() in semantic for marker in self.SENSITIVE_FIELD_MARKERS):
                return SafetyAssessment(
                    True,
                    "即将填写密码、验证码、支付或身份信息，需要用户逐项接管确认",
                )
            return SafetyAssessment(False)
        if decision_kind not in {"click", "long_press"}:
            return SafetyAssessment(False)
        semantic = self._semantic_text(selector, elements)
        marker = next((item for item in self.FINAL_CONFIRMATION_MARKERS if item in semantic), "")
        if not marker:
            return SafetyAssessment(False)
        return SafetyAssessment(
            True,
            f"即将执行高风险最终动作“{marker}”，已停在提交前等待用户明确确认",
        )

    @staticmethod
    def _semantic_text(
        selector: dict[str, str] | None,
        elements: list[ScreenElement],
    ) -> str:
        selector = selector or {}
        pieces = [str(value) for value in selector.values() if value]
        identifier = selector.get("identifier", "").strip()
        text = selector.get("text", "").strip()
        kind = selector.get("type", "").strip()
        for element in elements:
            if identifier and element.identifier != identifier:
                continue
            if kind and kind not in element.type:
                continue
            if text and not any(text in value for value in element.strings):
                continue
            pieces.extend(element.strings)
            pieces.append(element.identifier)
        return " ".join(pieces)
