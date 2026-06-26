"""Tortoise models mapping the existing Manager 360 Jira tables.

These models **describe**, they do not **define**: every table here is created
and migrated by the main Manager 360 application (SQLAlchemy + Alembic). The
``Meta.table`` names, column names, types and nullability are kept faithful to
that schema so the ingestion routine writes rows the main app can read back.
Schema generation is never invoked against this database.

Design notes:

* Only the entities needed for Delivery 360 sprint-metric ingestion are mapped
  (dimensions, boards, sprints, issues, sprint membership, issue field changes)
  plus the sync bookkeeping tables. Worklogs, comments, links, snapshots and the
  pre-computed metric tables are out of scope for this routine.
* Foreign keys are mapped as plain integer columns (``*_id``) rather than
  Tortoise relational fields. Ingestion resolves a related row, reads its ``id``
  and assigns the integer — relational navigation is not needed here and this
  keeps the mapping a 1:1 reflection of the physical columns.
* ``created_at`` / ``updated_at`` (added to every table by the main app's Base)
  are intentionally not declared: ``created_at`` is filled by the column's
  server default on insert, and ``updated_at`` stays NULL unless a later
  upsert path sets it explicitly.
"""

from tortoise import fields
from tortoise.models import Model

from ingestion.enums import (
    JiraBoardType,
    JiraSprintState,
    JiraSyncEntityType,
    JiraSyncRunStatus,
    JiraSyncTrigger,
)


# --- Configuration ---------------------------------------------------------


class TrackedJiraTeam(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255)
    key = fields.CharField(max_length=64, unique=True)
    jira_board_id = fields.IntField(null=True)
    is_active = fields.BooleanField(default=True)
    tracking_start_date = fields.DateField(null=True)
    description = fields.CharField(max_length=500, null=True)

    class Meta:  # type: ignore
        table = "tracked_jira_teams"


# --- Dimensions ------------------------------------------------------------


class JiraUser(Model):
    id = fields.IntField(pk=True)
    account_id = fields.CharField(max_length=128, unique=True)
    display_name = fields.CharField(max_length=255, null=True)
    email_address = fields.CharField(max_length=255, null=True)
    is_active = fields.BooleanField(default=True)
    timezone = fields.CharField(max_length=64, null=True)
    avatar_url = fields.CharField(max_length=500, null=True)
    first_seen_at = fields.DatetimeField(null=True)
    last_seen_at = fields.DatetimeField(null=True)
    raw_payload: dict | None = fields.JSONField(null=True)

    class Meta:  # type: ignore
        table = "jira_users"


class JiraIssueType(Model):
    id = fields.IntField(pk=True)
    jira_issue_type_id = fields.CharField(max_length=64, unique=True)
    name = fields.CharField(max_length=128)
    is_subtask = fields.BooleanField(default=False)
    icon_url = fields.CharField(max_length=500, null=True)

    class Meta:  # type: ignore
        table = "jira_issue_types"


class JiraStatus(Model):
    id = fields.IntField(pk=True)
    jira_status_id = fields.CharField(max_length=64, unique=True)
    name = fields.CharField(max_length=128)
    status_category_key = fields.CharField(max_length=32)
    status_category_name = fields.CharField(max_length=64, null=True)

    class Meta:  # type: ignore
        table = "jira_statuses"


class JiraPriority(Model):
    id = fields.IntField(pk=True)
    jira_priority_id = fields.CharField(max_length=64, unique=True)
    name = fields.CharField(max_length=64)
    icon_url = fields.CharField(max_length=500, null=True)

    class Meta:  # type: ignore
        table = "jira_priorities"


# --- Boards & sprints ------------------------------------------------------


class JiraBoard(Model):
    id = fields.IntField(pk=True)
    team_id = fields.IntField(index=True)
    jira_board_id = fields.IntField(unique=True)
    name = fields.CharField(max_length=255)
    board_type = fields.CharEnumField(JiraBoardType)
    is_deleted = fields.BooleanField(default=False)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:  # type: ignore
        table = "jira_boards"


class JiraSprint(Model):
    id = fields.IntField(pk=True)
    board_id = fields.IntField(index=True)
    team_id = fields.IntField(index=True)
    jira_sprint_id = fields.IntField(unique=True)
    name = fields.CharField(max_length=255)
    state = fields.CharEnumField(JiraSprintState)
    goal = fields.TextField(null=True)
    start_date = fields.DatetimeField(null=True)
    end_date = fields.DatetimeField(null=True)
    complete_date = fields.DatetimeField(null=True)
    is_deleted = fields.BooleanField(default=False)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:  # type: ignore
        table = "jira_sprints"


# --- Issues & facts --------------------------------------------------------


class JiraIssue(Model):
    id = fields.IntField(pk=True)
    team_id = fields.IntField(index=True)
    jira_issue_id = fields.CharField(max_length=64, unique=True)
    issue_key = fields.CharField(max_length=64, unique=True)
    issue_type_id = fields.IntField(null=True)
    status_id = fields.IntField(null=True)
    priority_id = fields.IntField(null=True)
    summary = fields.CharField(max_length=500)
    description = fields.TextField(null=True)
    story_points = fields.FloatField(null=True)
    parent_issue_id = fields.IntField(null=True)
    epic_issue_id = fields.IntField(null=True)
    assignee_id = fields.IntField(null=True)
    reporter_id = fields.IntField(null=True)
    creator_id = fields.IntField(null=True)
    resolution_name = fields.CharField(max_length=64, null=True)
    resolved_at = fields.DatetimeField(null=True)
    due_date = fields.DateField(null=True)
    jira_created_at = fields.DatetimeField()
    jira_updated_at = fields.DatetimeField()
    is_deleted = fields.BooleanField(default=False)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:  # type: ignore
        table = "jira_issues"


class JiraSprintIssue(Model):
    id = fields.IntField(pk=True)
    sprint_id = fields.IntField(index=True)
    issue_id = fields.IntField(index=True)
    added_at = fields.DatetimeField()
    removed_at = fields.DatetimeField(null=True)
    added_during_sprint = fields.BooleanField(default=False)
    committed = fields.BooleanField(default=False)
    completed_in_sprint = fields.BooleanField(default=False)
    story_points_at_addition = fields.FloatField(null=True)
    story_points_at_removal = fields.FloatField(null=True)

    class Meta:  # type: ignore
        table = "jira_sprint_issues"


class JiraIssueFieldChange(Model):
    id = fields.IntField(pk=True)
    issue_id = fields.IntField(index=True)
    jira_changelog_id = fields.CharField(max_length=64, null=True)
    field_name = fields.CharField(max_length=128)
    field_id = fields.CharField(max_length=128, null=True)
    field_type = fields.CharField(max_length=64, null=True)
    from_value = fields.TextField(null=True)
    from_value_id = fields.CharField(max_length=255, null=True)
    to_value = fields.TextField(null=True)
    to_value_id = fields.CharField(max_length=255, null=True)
    changed_at = fields.DatetimeField()
    changed_by_id = fields.IntField(null=True)
    source_sync_run_id = fields.IntField(null=True)

    class Meta:  # type: ignore
        table = "jira_issue_field_changes"
        unique_together = (("issue_id", "jira_changelog_id", "field_name"),)


# --- Sync metadata ---------------------------------------------------------


class JiraSyncRun(Model):
    id = fields.IntField(pk=True)
    team_id = fields.IntField(null=True)
    entity_type = fields.CharEnumField(JiraSyncEntityType)
    status = fields.CharEnumField(JiraSyncRunStatus, default=JiraSyncRunStatus.RUNNING)
    triggered_by = fields.CharEnumField(
        JiraSyncTrigger, default=JiraSyncTrigger.SCHEDULED
    )
    started_at = fields.DatetimeField()
    finished_at = fields.DatetimeField(null=True)
    records_fetched = fields.IntField(default=0)
    records_created = fields.IntField(default=0)
    records_updated = fields.IntField(default=0)
    records_deleted = fields.IntField(default=0)
    records_failed = fields.IntField(default=0)
    error_message: str | None = fields.TextField(null=True)

    class Meta:  # type: ignore
        table = "jira_sync_runs"


class JiraSyncState(Model):
    id = fields.IntField(pk=True)
    team_id = fields.IntField(index=True)
    entity_type = fields.CharEnumField(JiraSyncEntityType)
    last_synced_at = fields.DatetimeField(null=True)
    last_entity_updated_at = fields.DatetimeField(null=True)
    last_cursor = fields.CharField(max_length=500, null=True)
    last_run_status = fields.CharEnumField(JiraSyncRunStatus, null=True)
    last_run_id = fields.IntField(null=True)
    error_message: str | None = fields.TextField(null=True)

    class Meta:  # type: ignore
        table = "jira_sync_state"
        unique_together = (("team_id", "entity_type"),)
