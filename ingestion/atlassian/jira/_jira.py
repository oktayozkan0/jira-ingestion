from ingestion.atlassian.client._atlassian import Atlassian
from ingestion.atlassian.jira._boards import Boards
from ingestion.atlassian.jira._issues import Issues
from ingestion.atlassian.jira._projects import Projects
from ingestion.atlassian.jira._sprints import Sprints
from ingestion.atlassian.jira._users import Users
from ingestion.atlassian.jira._worklogs import Worklogs


class Jira(Atlassian):
    @property
    def issues(self) -> Issues:
        return Issues(self)

    @property
    def worklogs(self) -> Worklogs:
        return Worklogs(self)

    @property
    def users(self) -> Users:
        return Users(self)

    @property
    def projects(self) -> Projects:
        return Projects(self)

    @property
    def boards(self) -> Boards:
        return Boards(self)

    @property
    def sprints(self) -> Sprints:
        return Sprints(self)
