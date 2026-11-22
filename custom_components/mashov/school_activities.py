"""Parent approvals for school activities (Mashov "אישורי הורים לפעילות").

Fetching is GET-only and has no side effects at Mashov. Answering is the single
write action of this integration: it is off unless the hub option
``allow_write_actions`` is enabled, and refuses activities whose answer deadline
has passed or that ask extra questions (not supported yet).
"""

from __future__ import annotations

from datetime import date
import logging

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN
from .data_selection import CONF_ALLOW_WRITE_ACTIONS
from .mailbox import plain_body

_LOGGER = logging.getLogger(__name__)

DATA_KEY = "school_activities"
ANSWER_CODES = {"approved": 1, "approved_with_health_conditions": 2, "denied": 3}
_ANSWER_NAMES = {code: name for name, code in ANSWER_CODES.items()}
_TEXT_FIELDS = {
    "title": "title",
    "createTime": "create_time",
    "activityStartDate": "start_date",
    "activityEndDate": "end_date",
    "endAnswerDate": "end_answer_date",
}
REMARK_MAX_LENGTH = 500

ANSWER_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Required("activity_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("student"): cv.string,
        vol.Required("answer"): vol.In(ANSWER_CODES),
        vol.Optional("remark", default=""): vol.All(cv.string, vol.Length(max=REMARK_MAX_LENGTH)),
    }
)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _date_part(value):
    """Return the calendar date of an ISO timestamp, or None when absent/invalid."""
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def deadline_passed(end_answer_date, today):
    """Mirror the web app: answering closes after the deadline's day (UTC)."""
    deadline = _date_part(end_answer_date)
    return deadline is not None and deadline < today


def _activity(raw, today):
    """Parse one permitted activity; None when the payload shape is unexpected."""
    if not isinstance(raw, dict) or not _is_int(raw.get("id")) or not isinstance(raw.get("isAnswered"), bool):
        return None
    item = {"id": raw["id"], "is_answered": raw["isAnswered"]}
    for source, target in _TEXT_FIELDS.items():
        value = raw.get(source)
        if value is not None and not isinstance(value, str):
            return None
        item[target] = value
    item["activity_type"] = raw.get("activityType") if _is_int(raw.get("activityType")) else None
    item["description"] = plain_body(raw["description"]) if isinstance(raw.get("description"), str) else ""
    item["answer_deadline_passed"] = deadline_passed(item["end_answer_date"], today)
    return item


def _answer(row):
    """Normalize one student's answer row; None when the shape is unexpected."""
    answer = row.get("schoolActivityAnswer")
    if answer is None:
        return {"answer": None, "answered_at": None, "manually_answered": False}
    if not isinstance(answer, dict):
        return None
    answered_at = answer.get("answerTime")
    return {
        "answer": _ANSWER_NAMES.get(answer.get("answer")),
        "answered_at": answered_at if isinstance(answered_at, str) else None,
        "manually_answered": answer.get("manuallyAnswered") is True,
    }


def parse_answers(raw):
    """Map student GUID -> answer. The row's outer userId is the student."""
    result = {}
    for row in raw:
        normalized = _answer(row) if isinstance(row, dict) and isinstance(row.get("userId"), str) else None
        if normalized is None:
            return None
        result[row["userId"]] = normalized
    return result


def has_questions(raw):
    """Activities with a questionnaire carry a JSON string in activityData."""
    detail = raw[0] if raw and isinstance(raw[0], dict) else {}
    return isinstance(detail.get("activityData"), str) and bool(detail["activityData"].strip())


async def _add_answers(get_json, item):
    status, payload = await get_json(
        f"schoolActivities/{item['id']}/userAnswers", f"activity_{item['id']}_answers", list
    )
    answers = parse_answers(payload) if status == "ok" else None
    item["answers_status"] = "invalid_response" if status == "ok" and answers is None else status
    item["answers"] = answers or {}


async def _add_details(get_json, item):
    status, payload = await get_json(f"schoolActivities/{item['id']}/permitted", f"activity_{item['id']}_details", list)
    item["details_status"] = status
    # Unknown questionnaire state is treated as "has questions" by the answer service.
    item["has_questions"] = has_questions(payload) if status == "ok" else None


async def fetch_school_activities(get_json, *, limit, today):
    """Fetch the newest ``limit`` permitted activities with per-student answers.

    get_json(path, key, expected_type) -> (status, payload) handles auth and
    backoff. Every request here is a GET without side effects.
    """
    result = {"status": "not_fetched", "items": [], "limit": limit}
    status, payload = await get_json("schoolActivities/permitted", DATA_KEY, list)
    result["status"] = status
    if status != "ok":
        return result
    parsed = [_activity(raw, today) for raw in payload]
    if any(item is None for item in parsed):
        result["status"] = "invalid_response"
    items = sorted((item for item in parsed if item), key=lambda item: item["create_time"] or "", reverse=True)
    for item in items[:limit]:
        await _add_answers(get_json, item)
        await _add_details(get_json, item)
        result["items"].append(item)
    return result


def is_pending(item):
    """Still waiting for this parent and still answerable."""
    return not item.get("is_answered") and not item.get("answer_deadline_passed")


def display_items(items, *, show_ended, hide_answered, newest_first, today):
    """Apply the portal's list toggles; display only, never changes what is fetched."""
    shown = [
        item
        for item in items
        if (show_ended or not (_date_part(item.get("end_date")) or today) < today)
        and not (hide_answered and item.get("is_answered"))
    ]
    return sorted(shown, key=lambda item: item.get("create_time") or "", reverse=newest_first)


def _loaded_hub(hass, entry_id):
    """A write must target one loaded hub unambiguously."""
    hubs = {
        key: value
        for key, value in hass.data.get(DOMAIN, {}).items()
        if isinstance(value, dict) and "coordinator" in value
    }
    if entry_id:
        if entry_id not in hubs:
            raise ServiceValidationError(f"Mashov hub {entry_id} is not loaded")
        return hubs[entry_id]
    if len(hubs) != 1:
        raise ServiceValidationError("Specify entry_id: zero or several Mashov hubs are loaded")
    return next(iter(hubs.values()))


def _answerable_activity(data, activity_id):
    resource = (data or {}).get(DATA_KEY, {})
    activity = next((item for item in resource.get("items", []) if item.get("id") == activity_id), None)
    if activity is None:
        raise ServiceValidationError("Unknown school activity; refresh the data and use an id from the sensor")
    if activity.get("answer_deadline_passed"):
        raise ServiceValidationError("The answer deadline for this activity has passed")
    if activity.get("has_questions") is not False:
        raise ServiceValidationError("This activity has questions; answer it in the Mashov portal")
    return activity


def _student_id(data, student, activity):
    match = next(
        (s["id"] for s in (data or {}).get("students", []) if student in (str(s.get("id")), s.get("slug"))),
        None,
    )
    if match is None:
        raise ServiceValidationError("Unknown student for this hub")
    if activity.get("answers_status") == "ok" and match not in activity.get("answers", {}):
        raise ServiceValidationError("This activity does not apply to the selected student")
    return match


async def async_handle_answer(hass, call):
    """Service handler for mashov.answer_school_activity (admin only)."""
    from .mashov_client import MashovError

    hub = _loaded_hub(hass, call.data.get("entry_id"))
    coordinator, client = hub["coordinator"], hub["client"]
    if not coordinator.entry.options.get(CONF_ALLOW_WRITE_ACTIONS, False):
        raise ServiceValidationError("Enable 'Allow actions in Mashov' in the hub options first")
    activity = _answerable_activity(coordinator.data, call.data["activity_id"])
    student_id = _student_id(coordinator.data, call.data["student"], activity)
    try:
        await client.async_answer_school_activity(
            activity["id"], student_id, ANSWER_CODES[call.data["answer"]], call.data["remark"]
        )
    except MashovError as err:
        raise HomeAssistantError(str(err)) from err
    await coordinator.async_refresh_datasets({DATA_KEY})
