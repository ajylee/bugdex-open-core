from pytest import fixture, raises
import jira

import bugdex.environment_tools
from bugdex.core import deep_delete_source_specific_bug
from bugdex.jira_tools import (
    connect_to_jira,
    deep_create_jira_bug,
    JiraBug,
    BugdexJiraFields,
    update_bug,
)

bugdex.environment_tools.set_aws_profile()


@fixture
def jira_fields():
    return BugdexJiraFields(
        summary='[bugdex] Test Issue',
        description='test description',
        labels={'BugdexToDelete', 'BugdexTestLabel'},
    )


@fixture
def jira_server() -> jira.JIRA:
    return connect_to_jira()


@fixture
def jira_bug(jira_server: jira.JIRA):
    _jira_bug = deep_create_jira_bug(jira_server)

    _id = _jira_bug.id
    yield _jira_bug

    _jira_bug.to_raw_issue(jira_server).delete()
    deep_delete_source_specific_bug(_jira_bug)


def test_create_and_delete_jira_bug(jira_server: jira.JIRA):
    _jira_bug = deep_create_jira_bug(jira_server)

    _id = _jira_bug.id

    _jira_bug.to_raw_issue(jira_server).delete()
    deep_delete_source_specific_bug(_jira_bug)

    with raises(jira.exceptions.JIRAError):
        jira_server.issue(_id)


def test_fill_in_jira_bug(jira_server: jira.JIRA, jira_bug: JiraBug, jira_fields: BugdexJiraFields):
    update_bug(jira_server, jira_bug, jira_fields)
    issue = jira_bug.to_raw_issue(jira_server)

    assert issue.fields.description == jira_fields.description
    assert issue.fields.summary == jira_fields.summary
    assert jira_fields.labels <= set(issue.fields.labels)
