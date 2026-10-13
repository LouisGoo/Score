"""在持有活动锁的业务事务内推进角色版本；私人改分不推进他人流。"""

from sqlalchemy import update

from score_api.events.models import EventJudge


def advance_views(session, event, *, judge_id=None, public=True):
    if public:
        event.screen_version += 1
        query = update(EventJudge).where(EventJudge.event_id == event.id)
    else:
        query = update(EventJudge).where(EventJudge.event_id == event.id, EventJudge.id == judge_id)
    session.execute(query.values(snapshot_version=EventJudge.snapshot_version + 1))


def automatic_screen(event, action, row=None):
    if action in {"open", "resume", "round.reopened"}:
        event.screen_mode, event.screen_round_id = "progress", row.id
    elif action == "pause":
        event.screen_mode, event.screen_round_id = "paused", row.id
    elif action == "result.published":
        event.screen_mode, event.screen_round_id = "result", row.id
    elif action in {"round.closed", "round.no_result"} and event.screen_round_id == row.id:
        event.screen_mode, event.screen_round_id = "waiting", None
    elif action == "event.finished":
        event.screen_mode, event.screen_round_id = "ended", None
