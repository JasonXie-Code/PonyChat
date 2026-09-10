"""App 登录管控白名单。"""

ALLOWED_APP_LOGIN_USERS = frozenset({"Jason", "System"})

LOGIN_CONTROL_MESSAGE = "当前账号暂时无法登录"
LOGIN_CONTROL_LOGOUT_REASON = "login_control"


def is_app_login_allowed(username: str) -> bool:
    """仅允许明确列入白名单的账号登录或继续使用现有登录态。"""
    return str(username or "") in ALLOWED_APP_LOGIN_USERS
