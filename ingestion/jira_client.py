"""Factory for the Jira API client, configured from settings.

Keeping construction in one place means every ingester gets the same timeouts,
retry budget, and rate-limit handling, and the credentials are read only from
the environment-backed settings.
"""

from ingestion.atlassian.jira import Jira
from ingestion.config import settings


def build_jira() -> Jira:
    """Build a Jira client. Use as an async context manager::

    async with build_jira() as jira:
        ...
    """
    return Jira(
        base_url=settings.jira_base_url,
        email=settings.jira_email,
        api_token=settings.jira_api_token,
        read_timeout=settings.jira_read_timeout,
        connect_timeout=settings.jira_connect_timeout,
        max_retries=settings.jira_max_retries,
        retry_on_rate_limit=True,
        rate_limit_max_wait=settings.jira_rate_limit_max_wait,
    )
