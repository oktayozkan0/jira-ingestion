"""Enums mirroring the Jira schema owned by the main Manager 360 app.

The main app defines these with SQLAlchemy's ``Enum`` type, which persists the
enum member **name** (uppercase) to the database. Tortoise's ``CharEnumField``,
by contrast, persists the member **value**. To write the exact same strings the
main app reads, the member values here are the uppercase names — e.g.
``JiraBoardType.SCRUM.value == "SCRUM"``.

Only the enums needed for the in-scope ingestion entities are defined here;
metric-related enums (e.g. period type) are intentionally omitted.
"""

from enum import Enum


class JiraBoardType(str, Enum):
    SCRUM = "SCRUM"
    KANBAN = "KANBAN"
    SIMPLE = "SIMPLE"


class JiraSprintState(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    FUTURE = "FUTURE"


class JiraSyncEntityType(str, Enum):
    BOARDS = "BOARDS"
    SPRINTS = "SPRINTS"
    ISSUES = "ISSUES"
    ISSUE_TYPES = "ISSUE_TYPES"
    STATUSES = "STATUSES"
    PRIORITIES = "PRIORITIES"
    USERS = "USERS"
    LABELS = "LABELS"
    COMPONENTS = "COMPONENTS"
    WORKLOGS = "WORKLOGS"
    COMMENTS = "COMMENTS"
    ATTACHMENTS = "ATTACHMENTS"
    ISSUE_LINKS = "ISSUE_LINKS"


class JiraSyncRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class JiraSyncTrigger(str, Enum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"
    BACKFILL = "BACKFILL"
