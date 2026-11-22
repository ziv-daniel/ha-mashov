"""School activity approvals: GET-only fetching, display toggles, and the opt-in answer write."""

from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest

from custom_components.mashov.data_selection import filter_cached_data, merge_selection_options
from custom_components.mashov.mashov_client import MashovClient, MashovError, MashovPasswordChangeRequiredError
from custom_components.mashov.school_activities import display_items, fetch_school_activities
from custom_components.mashov.sensor import MashovSchoolActivitiesSensor

from .const import (
    ACTIVITY_DETAIL_QUESTIONS,
    ACTIVITY_DETAIL_SIMPLE,
    ACTIVITY_OTHER_STUDENT,
    ACTIVITY_PARENT,
    ACTIVITY_STUDENT,
    ACTIVITY_TODAY,
    ACTIVITY_USER_ANSWERS,
    PERMITTED_ACTIVITIES,
)
from .test_roster_change import _response

TODAY = date.fromisoformat(ACTIVITY_TODAY)


def portal(permitted=PERMITTED_ACTIVITIES, answers=ACTIVITY_USER_ANSWERS, detail=ACTIVITY_DETAIL_SIMPLE):
    """get_json stand-in routing by path, like MashovClient._fetch_account_json."""

    async def get(path, key, expected):
        if path == "schoolActivities/permitted":
            return "ok", deepcopy(permitted)
        if path.endswith("/userAnswers"):
            return ("ok", deepcopy(answers)) if answers is not None else ("forbidden", None)
        return ("ok", deepcopy(detail)) if detail is not None else ("http_500", None)

    return AsyncMock(side_effect=get)


async def fetched(**kwargs):
    return await fetch_school_activities(portal(**kwargs), limit=20, today=TODAY)


async def test_parses_activities_answers_and_deadline():
    result = await fetched()
    assert result["status"] == "ok"
    trip, museum = result["items"]
    assert (trip["id"], museum["id"]) == (12, 7)  # newest first
    assert trip["description"] == "Bring water"
    assert trip["answer_deadline_passed"] is False
    assert museum["answer_deadline_passed"] is True
    assert trip["has_questions"] is False
    assert trip["answers"][ACTIVITY_STUDENT] == {
        "answer": "approved",
        "answered_at": "2026-11-17T08:00:00",
        "manually_answered": False,
    }
    assert trip["answers"][ACTIVITY_OTHER_STUDENT]["answer"] is None


async def test_questionnaire_and_unknown_detail_are_flagged():
    assert (await fetched(detail=ACTIVITY_DETAIL_QUESTIONS))["items"][0]["has_questions"] is True
    unknown = (await fetched(detail=None))["items"][0]
    assert unknown["has_questions"] is None
    assert unknown["details_status"] == "http_500"


async def test_malformed_records_are_isolated():
    result = await fetched(permitted=[{"id": "x"}, PERMITTED_ACTIVITIES[0]], answers=[{"no": "user"}])
    assert result["status"] == "invalid_response"
    assert [item["id"] for item in result["items"]] == [12]
    assert result["items"][0]["answers_status"] == "invalid_response"
    assert result["items"][0]["answers"] == {}


async def test_limit_bounds_requests_and_only_reads():
    get = portal()
    result = await fetch_school_activities(get, limit=1, today=TODAY)
    assert [item["id"] for item in result["items"]] == [12]
    assert [call.args[0] for call in get.await_args_list] == [
        "schoolActivities/permitted",
        "schoolActivities/12/userAnswers",
        "schoolActivities/12/permitted",
    ]


async def test_list_failure_skips_item_requests():
    get = AsyncMock(return_value=("forbidden", None))
    result = await fetch_school_activities(get, limit=20, today=TODAY)
    assert result == {"status": "forbidden", "items": [], "limit": 20}
    assert get.await_count == 1


async def test_display_toggles():
    items = (await fetched())["items"]
    ids = lambda **kw: [i["id"] for i in display_items(items, today=TODAY, **kw)]  # noqa: E731
    assert ids(show_ended=False, hide_answered=False, newest_first=True) == [12]
    assert ids(show_ended=True, hide_answered=False, newest_first=True) == [12, 7]
    assert ids(show_ended=True, hide_answered=True, newest_first=True) == [12]
    assert ids(show_ended=True, hide_answered=False, newest_first=False) == [7, 12]


async def sensor_for(options=None, status="ok"):
    data = {"school_activities": {**(await fetched()), "status": status}}
    coordinator = SimpleNamespace(
        data=data,
        entry=SimpleNamespace(title="Test", options=options or {}),
        last_update_success=True,
        data_stale=False,
        last_successful_update=None,
    )
    return MashovSchoolActivitiesSensor(coordinator, "entry")


async def test_sensor_counts_pending_and_lists_by_options():
    sensor = await sensor_for()
    assert sensor.native_value == 1
    attributes = sensor.extra_state_attributes
    assert [item["id"] for item in attributes["items"]] == [12]
    assert attributes["fetched_activities"] == 2
    assert attributes["allow_write_actions"] is False
    shown = (await sensor_for({"school_activities_show_ended": True})).extra_state_attributes
    assert [item["id"] for item in shown["items"]] == [12, 7]
    assert (await sensor_for(status="forbidden")).native_value is None


def test_deselecting_source_revokes_write_and_clears_cache():
    options = merge_selection_options(
        {"enabled_data": ["school_activities"], "allow_write_actions": True}, {"enabled_data": ["homework"]}
    )
    assert options["allow_write_actions"] is False
    cached = {"school_activities": {"items": [{"id": 1}, {"id": 2}]}}
    assert "school_activities" not in filter_cached_data(cached, options)
    limited = filter_cached_data(cached, {"enabled_data": ["school_activities"], "school_activities_limit": 1})
    assert limited["school_activities"]["items"] == [{"id": 1}]


def writer(*responses):
    client = MashovClient("123", 2027, "test", "test")
    client._auth_data = {"credential": {"userId": ACTIVITY_PARENT}}
    client._headers = {"Accept": "application/json", "X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._session.put.side_effect = list(responses)
    client._ensure_valid_session = AsyncMock()
    return client


async def test_answer_sends_portal_request_with_csrf_and_parent_id():
    client = writer(_response(200))
    await client.async_answer_school_activity(12, ACTIVITY_STUDENT, 2, "Asthma")
    args, kwargs = client._session.put.call_args
    assert args[0] == f"https://web.mashov.info/api/students/{ACTIVITY_STUDENT}/schoolActivities/12"
    assert kwargs["json"] == {
        "activityId": 12,
        "studentGuid": ACTIVITY_STUDENT,
        "userId": ACTIVITY_PARENT,
        "answer": 2,
        "remark": "Asthma",
    }
    assert kwargs["headers"]["X-Csrf-Token"] == "synthetic"
    client._session.get.assert_not_called()


async def test_answer_retries_once_after_401():
    client = writer(_response(401), _response(200))
    await client.async_answer_school_activity(12, ACTIVITY_STUDENT, 1)
    assert client._session.put.call_count == 2
    client._ensure_valid_session.assert_awaited_once()


async def test_answer_errors_do_not_expose_response_body():
    rejected = _response(500)
    (await rejected.__aenter__()).text = AsyncMock(return_value="private server text")
    with pytest.raises(MashovError, match="HTTP 500") as err:
        await writer(rejected).async_answer_school_activity(12, ACTIVITY_STUDENT, 1)
    assert "private" not in str(err.value)
    changepass = _response(403)
    (await changepass.__aenter__()).headers = {"reason": "changepass"}
    with pytest.raises(MashovPasswordChangeRequiredError):
        await writer(changepass).async_answer_school_activity(12, ACTIVITY_STUDENT, 1)


async def test_answer_without_parent_id_logs_in_then_refuses():
    client = writer(_response(200))
    client._auth_data = {}
    client.async_init = AsyncMock()
    with pytest.raises(MashovError, match="parent account id"):
        await client.async_answer_school_activity(12, ACTIVITY_STUDENT, 1)
    client.async_init.assert_awaited_once()
    client._session.put.assert_not_called()


async def install_hub(hass, *, options=None, detail=ACTIVITY_DETAIL_SIMPLE, permitted=PERMITTED_ACTIVITIES):
    assert await async_setup_component(hass, "mashov", {})
    activities = await fetch_school_activities(portal(permitted=permitted, detail=detail), limit=20, today=TODAY)
    coordinator = SimpleNamespace(
        entry=SimpleNamespace(options={"allow_write_actions": True} if options is None else options),
        data={"students": [{"id": ACTIVITY_STUDENT, "slug": "kid"}], "school_activities": activities},
        async_refresh_datasets=AsyncMock(),
    )
    client = SimpleNamespace(async_answer_school_activity=AsyncMock())
    hass.data["mashov"]["entry"] = {"coordinator": coordinator, "client": client}
    return coordinator, client


async def answer(hass, **overrides):
    call = {"activity_id": 12, "student": "kid", "answer": "approved_with_health_conditions", **overrides}
    await hass.services.async_call("mashov", "answer_school_activity", call, blocking=True)


async def test_service_answers_and_refreshes_only_activities(hass):
    coordinator, client = await install_hub(hass)
    await answer(hass, remark="Asthma")
    client.async_answer_school_activity.assert_awaited_once_with(12, ACTIVITY_STUDENT, 2, "Asthma")
    coordinator.async_refresh_datasets.assert_awaited_once_with({"school_activities"})


@pytest.mark.parametrize(
    ("hub", "call", "message"),
    [
        ({"options": {}}, {}, "Allow actions"),
        ({}, {"activity_id": 99}, "Unknown school activity"),
        ({}, {"activity_id": 7}, "deadline"),
        ({"detail": ACTIVITY_DETAIL_QUESTIONS}, {}, "questions"),
        ({"detail": None}, {}, "questions"),
        ({}, {"student": "someone-else"}, "Unknown student"),
    ],
)
async def test_service_refuses_unsafe_answers(hass, hub, call, message):
    _, client = await install_hub(hass, **hub)
    with pytest.raises(ServiceValidationError, match=message):
        await answer(hass, **call)
    client.async_answer_school_activity.assert_not_awaited()


async def test_service_refuses_student_outside_activity(hass):
    coordinator, client = await install_hub(hass)
    coordinator.data["students"].append({"id": "outsider", "slug": "outsider"})
    with pytest.raises(ServiceValidationError, match="does not apply"):
        await answer(hass, student="outsider")
    client.async_answer_school_activity.assert_not_awaited()


async def test_service_reports_portal_failure_without_refresh(hass):
    coordinator, client = await install_hub(hass)
    client.async_answer_school_activity.side_effect = MashovError("Mashov rejected the answer (HTTP 500)")
    with pytest.raises(HomeAssistantError, match="HTTP 500"):
        await answer(hass)
    coordinator.async_refresh_datasets.assert_not_awaited()


async def test_service_needs_entry_id_with_several_hubs(hass):
    _, client = await install_hub(hass)
    hass.data["mashov"]["second"] = {"coordinator": object()}
    with pytest.raises(ServiceValidationError, match="entry_id"):
        await answer(hass)
    client.async_answer_school_activity.assert_not_awaited()


async def test_set_options_requires_source_for_write(hass, mock_config_entry):
    # Added after component setup, so the hub is not loaded and no login is attempted.
    assert await async_setup_component(hass, "mashov", {})
    mock_config_entry.add_to_hass(hass)
    with pytest.raises(ServiceValidationError, match="school activities"):
        await hass.services.async_call(
            "mashov", "set_options", {"enabled_data": ["homework"], "allow_write_actions": True}, blocking=True
        )
    assert "allow_write_actions" not in mock_config_entry.options


async def test_fetched_payload_has_no_parent_id():
    assert ACTIVITY_PARENT not in json.dumps(await fetched())


async def test_options_flow_requires_source_and_revokes_on_deselect(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"enabled_data": ["homework"], "allow_write_actions": True}
    )
    assert result["errors"]["data"]["allow_write_actions"] == "school_activities_required"
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"enabled_data": ["school_activities"], "allow_write_actions": True}
    )
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"enabled_data": ["homework"], "allow_write_actions": True}
    )
    assert result["type"] == "create_entry"
    assert mock_config_entry.options["allow_write_actions"] is False
