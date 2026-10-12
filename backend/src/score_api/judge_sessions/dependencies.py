from fastapi import Request

from score_api.auth.dependencies import check_csrf, database_for
from score_api.judge_sessions.service import get_principal


def cookie_name(request, purpose):
    return (
        ("__Host-" if request.app.state.settings.cookie_secure else "") + "score_judge_" + purpose
    )


def require_judge(request: Request):
    principal = get_principal(
        database_for(request),
        request.cookies.get(cookie_name(request, "session"), ""),
        request.app.state.clock(),
    )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_csrf(request, principal.info.csrf_token)
    return principal
