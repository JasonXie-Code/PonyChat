"""Login availability policy; authentication remains in the auth routes."""

LOGIN_CONTROL_MESSAGE = "当前账号暂时无法登录"
LOGIN_CONTROL_LOGOUT_REASON = "login_control"


def is_app_login_allowed(username: str) -> bool:
    """All usernames may authenticate; no account allowlist is enforced."""
    return True
