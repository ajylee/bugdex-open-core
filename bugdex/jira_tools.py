from __future__ import annotations

import operator
from io import BytesIO
from itertools import chain
from pathlib import Path
from typing import Dict, Any, Final, Iterable, Tuple, AbstractSet, IO, Optional, TYPE_CHECKING, Mapping, Union, ClassVar
from uuid import uuid4

import attr
import toolz
from immutables import Map
from more_itertools import one

import pynamodb.models
from jira import JIRA, Issue, Project, JIRAError, Priority
from jira.client import ResultList
from jira.resources import IssueType, IssueLinkType, Component
from pandas._libs import json
from pynamodb.attributes import UnicodeAttribute
import pytz
import datetime

from toolz import merge

contains = toolz.curry(operator.contains)

config = json.loads(Path('~/.config/bugdex.json').read_text())


class JiraBug(pynamodb.models.Model):
    id = UnicodeAttribute(hash_key=True)
    key = UnicodeAttribute()
    project = UnicodeAttribute()
    summary = UnicodeAttribute()
    description = UnicodeAttribute(null=True)
    issuetype = UnicodeAttribute()
    universal_id = UnicodeAttribute(null=True)

    table_parameter_name = "/tables/bugdex/jira_bugs"

    class Meta:
        table_name = "bugdex_jira_bugs_v1"
        region = "us-west-2"

    @classmethod
    def from_issue_dict(cls, issue_key, issue_dict):
        return cls(
            key=issue_key,
            project=issue_dict['project']['id'],
            summary=issue_dict['summary'],
            description=issue_dict['description'],
            issuetype=issue_dict['issuetype']['name'],
        )

    @classmethod
    def from_raw_issue(cls, issue: Issue):
        for existing_bug in cls.query(issue.id):
            if existing_bug.universal_id:
                universal_id = existing_bug.universal_id
                break
        else:
            universal_id = str(uuid4()).lower()

        return cls(
            id=issue.id,
            key=issue.key,
            project=issue.fields.project.key,
            summary=issue.fields.summary,
            description=issue.fields.description,
            issuetype=issue.fields.issuetype.name,
            universal_id=universal_id,
        )

    def to_raw_issue(self, jira_server: JIRA):
        return jira_server.issue(self.key)

    @classmethod
    def ingest(cls, jira_server: JIRA, issues: Iterable[Issue] = ()) -> Iterable[JiraBug]:
        from .core import UniversalBug

        jql_str = """
        (labels = AppSec)
        AND (resolution is EMPTY OR status in (Reopened))
        AND status not in (Closed, Resolved) ORDER BY summary ASC, created ASC
        """.strip()

        if not issues:
            issues = chain(
                search_issues_with_scrolling(jira_server, jql_str),
            )

        visited = set()

        for issue in issues:
            if issue.key in visited:
                continue
            bug = cls.from_raw_issue(issue)
            bug.save()
            UniversalBug.propose(
                universal_id=bug.universal_id,
                source='jira',
                source_specific_id=bug.id,
            )
            yield bug
            visited.add(bug.key)

    @classmethod
    def ingest_one(cls, jira_server: JIRA, issue: Issue, canonical_bug=None):
        from .core import UniversalBug

        bug = cls.from_raw_issue(
            issue if isinstance(issue, Issue) else jira_server.issue(issue['id'])
        )
        bug.save()
        UniversalBug.propose(
            universal_id=bug.universal_id,
            source='jira',
            source_specific_id=bug.id,
            canonical_bug=canonical_bug,
        )
        return bug


# ----


def connect_to_jira(url=config["jira_url"]) -> JIRA:
    from .environment_tools import get_session
    ssm = get_session().client('ssm', region_name='us-east-1')

    # ssm.describe_parameters()
    username = ssm.get_parameter(Name=config["path_to_jira_username"], WithDecryption=True)['Parameter']['Value']
    password = ssm.get_parameter(Name=config["path_to_jira_password"], WithDecryption=True)['Parameter']['Value']

    jira_server = JIRA(options={"server": url}, auth=(username, password))
    return jira_server


def get_projects(jira_server: JIRA) -> Dict[str, Project]:
    return {project.key: project for project in jira_server.projects()}


# another interesting field: attachment
jira_search_default_output_fields: Final = ["id", "key", "project", "summary", "description", "issuetype"]


def search_issues_with_scrolling(jira_server, jql_str, maxResults=False, fields=None) -> ResultList:
    """Better defaults for JIRA.search_issues

    Like JIRA.search_issues, but always return ResultList and default to trying to returning all issues in batches

    :param jira_server: JIRA object
    :param jql_str: query string
    :param maxResults:  default is False -- try to get all issues in batches
    :return: ResultList
    """

    if fields is None:
        fields = ','.join(jira_search_default_output_fields)

    return jira_server.search_issues(
        jql_str=jql_str,
        json_result=False,
        fields=fields,
        startAt=0,
        maxResults=maxResults,
    )


progression = {
    'NeedsPriority': 'ZSecPrioritized',
    'NeedsAssignment': 'ZSecAssigned',
    'NeedsValidation': 'ZSecValidated',
}

triage_states = {
    'NeedsPriority',
    'NeedsAssignment',
    'NeedsValidation',
}


def expand_triage_label(labels):
    if 'Triage' in labels:
        for label, successor_label in progression.items():
            if successor_label not in labels:
                labels.add(label)


def transition_jira_issue(issue: Issue, state=None):
    """
    Note: if state is None, then this merely makes the labels self-consistent.

    :param issue:
    :param state:
    :return:
    """
    current_fields = issue.fields
    labels = set(current_fields.labels)

    if state is not None:
        assert state in progression.values()
        labels.discard('NeedsValidation')
        labels.add(state)

    expand_triage_label(labels)

    if {progression[triage_state] for triage_state in triage_states} <= labels:
        labels.remove('Triage')

    new_fields = {
        "labels": list(labels),
    }

    issue.update(fields=new_fields)


def add_labels(issue, labels):
    new_fields = {'labels': list(set(issue.fields.labels) | set(labels))}
    issue.update(fields=new_fields)


def deep_create_jira_bug(
        jira_server: JIRA, summary='[bugdex] BUGDEX PLACEHOLDER SUMMARY', description='Empty placeholder',
        canonical_bug=None,
):
    issue_dict = {
        'project': 'SECBUG',
        'summary': summary,
        'description': description,
        'issuetype': {'name': 'Bug'},
    }

    new_issue = jira_server.create_issue(fields=issue_dict)

    return JiraBug.ingest_one(jira_server, issue=new_issue, canonical_bug=canonical_bug)


auto_split_comment: Final = 'bugdex auto-split'
issue_split_id: Final[str] = config['issue_split_id']


def _add_attachment(issue: Issue, attachment: IO, filename: str):
    """
    JIRA.add_attachment is broken, because of improper use of CaseInsensitiveDict. Therefore, reimplement it.
    The fix is to only use lower-cased keys with CaseInsensitiveDict.
    """

    from jira.utils import CaseInsensitiveDict
    from requests_toolbelt import MultipartEncoder

    self = issue

    url = self._get_url('issue/' + str(self) + '/attachments')

    def file_stream():
        return MultipartEncoder(
            fields={
                'file': (filename, attachment, 'application/octet-stream')})

    m = file_stream()
    r = self._session.post(
        url, data=m, headers=CaseInsensitiveDict({'content-type': m.content_type, 'X-Atlassian-Token'.lower(): 'nocheck'}), retry_data=file_stream)


def _get_attachments(issue: Issue) -> AbstractSet[Tuple[str, bytes]]:
    return frozenset(
        (attachment.filename, attachment.get())
        for attachment in issue.fields.attachment
    )


def _copy_attachments(from_issue: Issue, to_issue: Issue):
    # copy any attachment not already attached to the new one, identifying attachments by filename and content

    for _filename, _content in _get_attachments(from_issue) - _get_attachments(to_issue):
        _add_attachment(to_issue, attachment=BytesIO(_content), filename=_filename)


def _get_split_issue(jira_server: JIRA, issue: Issue, new_project: Project) -> Optional[Issue]:
    for new_issue_link in filter(lambda ll: ll.type.id == issue_split_id, issue.fields.issuelinks):
        if new_issue := getattr(new_issue_link, 'outwardIssue', None):
            new_issue_fields = jira_server.issue(new_issue.id).fields
            if new_issue_fields.reporter.key == 'security.automation' and new_issue_fields.project.id == new_project.id:
                return new_issue

    return None


priority_id_to_sla = config['priority_id_to_sla']
"""
e.g. ::

    {
        '1': 1,
    }
"""

hq_tz = pytz.timezone('America/Los_Angeles')


def get_due_date(priority_id) -> Optional[datetime.date]:
    days = priority_id_to_sla[priority_id]
    if days is not None:
        return datetime.datetime.now(tz=hq_tz).date() + datetime.timedelta(days=days)
    else:
        return None


def split_issue(jira_server: JIRA, issue: Issue, new_project: Project, issue_type: IssueType, priority: Priority):
    """Split the issue to a new project and issue type; idempotent

    TODO: set the due date based on priority, copy some of the labels

    """

    issue_split: IssueLinkType = jira_server.issue_link_type(issue_split_id)

    valid_component_names = frozenset(component.name for component in new_project.components)

    labels_filter = {'AppSec', 'Bugdex'}

    fields = dict(
        summary=issue.fields.summary,
        description=issue.fields.description,
        components=[{'name': component.name} for component in issue.fields.components if component.name in valid_component_names],
        # attachment=issue.fields.attachment,
        project={'id': new_project.id},
        issuetype={'id': issue_type.id},
        priority={'id': priority.id},
        labels=list(set(issue.fields.labels) & labels_filter),
    )

    fields_duedate = dict(
        duedate=get_due_date(issue.fields.priority.id).strftime('%Y-%m-%d'),
    )

    _split_issue: Issue
    if _split_issue := _get_split_issue(jira_server, issue, new_project):
        new_issue_labels = set(jira_server.issue(_split_issue.id).fields.labels)
        fields.update(labels=list(set(fields['labels']) | new_issue_labels))
        _split_issue.update(fields=fields)
        print('updated issue:', _split_issue.permalink())
    else:
        _split_issue = jira_server.create_issue(fields=fields)
        print('created new issue:', _split_issue.permalink())
        # comment = dict(body=auto_split_comment, visibility=None)
        jira_server.create_issue_link(type=issue_split.name, inwardIssue=issue.key, outwardIssue=_split_issue.key)

    try:
        if not _split_issue.fields.duedate:
            _split_issue.update(fields=fields_duedate)
        else:
            print('not overriding duedate, otherwise would have set it to {}'.format(fields_duedate['duedate']))
    except JIRAError:
        print('could not set duedate, should be {}'.format(fields_duedate['duedate']))
        issue.update(fields=fields_duedate)

    _copy_attachments(issue, _split_issue)
    return _split_issue


@attr.s(auto_attribs=False)
class BugdexJiraFields:
    """Bugdex's internal representation of Jira Fields

    recommended components

    """

    summary: str = attr.ib()
    description: str = attr.ib()
    components: AbstractSet[Union[Component, Mapping]] = attr.ib(factory=set)
    labels: AbstractSet[str] = attr.ib(factory=set)
    issuetype: Mapping[str, str] = attr.ib(default=Map({'name': 'Bug'}))

    def to_jira_update_args(self) -> Mapping[str, Any]:
        from .serializing import CustomEncoder

        def raw(component):
            if isinstance(component, Component):
                return component.raw
            else:
                return component

        raw_components = {
            Map(toolz.keyfilter(lambda key: key in {'name', 'id'}, raw(component)))
            for component in self.components}

        raw_fields = toolz.assoc(attr.asdict(self), 'components', raw_components)

        return CustomEncoder().deep_represent(raw_fields)


def update_bug(jira_server: JIRA, bug: JiraBug, fields: BugdexJiraFields):
    issue = bug.to_raw_issue(jira_server)

    labels = set(fields.labels) | set(issue.fields.labels)

    if 'ZSecTriaged' not in labels:
        labels.add('ZSecNeedsTriage')

        if 'ZSecAssigned' not in labels:
            labels.add('ZSecNeedsAssignment')

        if 'ZSecPrioritized' not in labels:
            labels.add('ZSecNeedsPrioritization')

        if 'ZSecValidated' not in labels:
            labels.add('ZSecNeedsValidation')

    merged_fields = attr.evolve(fields, labels=labels)

    issue.update(fields=merged_fields.to_jira_update_args())
