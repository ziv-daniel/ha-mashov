"""Sample credentials and Mashov API payloads shared by the tests.

Values match the ``mock_config_entry`` and ``mock_mashov_client`` fixtures in conftest.
"""

# Test credentials
TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_SCHOOL_ID = "123456"
TEST_SCHOOL_NAME = "Test School"
TEST_YEAR = "2024"

# Test student data
TEST_STUDENT = {
    "childGuid": "student-123",
    "privateName": "Test",
    "lastName": "Student",
    "fullName": "Test Student",
}

# Test homework data
TEST_HOMEWORK = [
    {
        "lessonId": "lesson-1",
        "lesson_date": "2024-01-15T00:00:00",
        "lesson": 1,
        "groupId": "group-1",
        "subject_name": "Mathematics",
        "homework": "Page 10-15",
    }
]

# Test behavior data
TEST_BEHAVIOR = [
    {
        "lesson_date": "2024-01-15T00:00:00",
        "lesson": 1,
        "subject": "Mathematics",
        "achva_name": "Excellent participation",
        "teacher_name": "Test Teacher",
    }
]

# Test timetable data
TEST_TIMETABLE = [
    {
        "timeTable": {"day": 1, "lesson": 1, "groupId": "group-1"},
        "groupDetails": {"subjectName": "Mathematics", "groupName": "Math A"},
        "groupTeachers": [{"teacherName": "Test Teacher"}],
    }
]

# Test weekly plan data
TEST_WEEKLY_PLAN = [
    {
        "lesson_date": "2024-01-15T00:00:00",
        "lesson": 1,
        "group_id": "group-1",
        "plan": "Introduction to algebra",
    }
]

# Test holidays data
TEST_HOLIDAYS = [
    {
        "start": "2024-01-20T00:00:00",
        "end": "2024-01-21T00:00:00",
        "name": "Test Holiday",
    }
]

# --- School activities (parent approvals); shapes captured from the live portal, values synthetic ---
ACTIVITY_STUDENT = "11111111-0000-0000-0000-000000000001"
ACTIVITY_OTHER_STUDENT = "11111111-0000-0000-0000-000000000002"
ACTIVITY_PARENT = "22222222-0000-0000-0000-000000000001"
ACTIVITY_TODAY = "2026-11-23"
PERMITTED_ACTIVITIES = [
    {
        "id": 12,
        "createTime": "2026-11-16T09:00:00",
        "activityStartDate": "2026-11-25T00:00:00",
        "activityEndDate": "2026-11-25T00:00:00",
        "activityType": 1,
        "creatorGuid": "33333333-0000-0000-0000-000000000001",
        "title": "Class trip",
        "description": "<p>Bring water</p><script>x()</script>",
        "endAnswerDate": "2026-11-24T00:00:00",
        "isAnswered": False,
    },
    {
        "id": 7,
        "createTime": "2026-11-01T09:00:00",
        "activityStartDate": "2026-11-05T00:00:00",
        "activityEndDate": "2026-11-05T00:00:00",
        "activityType": 1,
        "creatorGuid": "33333333-0000-0000-0000-000000000001",
        "title": "Museum",
        "description": "Old",
        "endAnswerDate": "2026-11-04T00:00:00",
        "isAnswered": True,
    },
]
ACTIVITY_USER_ANSWERS = [
    {
        "userId": ACTIVITY_STUDENT,
        "schoolActivityAnswer": {
            "activityId": 12,
            "answer": 1,
            "answerTime": "2026-11-17T08:00:00",
            "manuallyAnswered": False,
            "studentGuid": ACTIVITY_STUDENT,
            "userId": ACTIVITY_PARENT,
        },
    },
    {"userId": ACTIVITY_OTHER_STUDENT},
]
ACTIVITY_DETAIL_SIMPLE = [{**PERMITTED_ACTIVITIES[0], "activityData": None}]
ACTIVITY_DETAIL_QUESTIONS = [{**PERMITTED_ACTIVITIES[0], "activityData": '{"questions": [{"q": "Allergies?"}]}'}]
