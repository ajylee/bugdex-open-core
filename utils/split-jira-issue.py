from functools import partial
from sys import stderr
from typing import Optional, Callable, Iterable

from more_itertools import one

import os

from bugdex.environment_tools import set_aws_profile
from bugdex.jira_tools import connect_to_jira
from bugdex.jira_tools import split_issue
from jira import JIRAError, Issue, JIRA, Priority

import argparse


def delete_issue(jira_server: JIRA, issue_id_or_key: str, condition: Optional[Callable[[Issue], bool]]) -> bool:
    """Delete an issue. Idempotent. Returns whether an action was taken.

    :param jira_server: self-explanatory
    :param issue_id_or_key: self-explanatory
    :param condition: Condition needs to be true to proceed with deleting the issue.

    """
    try:
        issue = jira_server.issue(issue_id_or_key)
    except JIRAError:
        return False
    else:
        if condition is None or condition(issue):
            print('deleting', issue.permalink())
            issue.delete()
            return True
        else:
            print('did not delete issue due to condition failing')
            return False


def get_cli_args():

    parser = argparse.ArgumentParser()

    parser.add_argument('issue_key', type=str, help='The issue to split. You can also pass an issue ID.')
    parser.add_argument('project_key', type=str,
                        help='Destination project key to split the issue into. For example, "PAY". Input will be upper cased before sending to Jira.')
    parser.add_argument('--issue-type', type=str, default='security bug', help='Issue type for the new bug. Defaults to "security bug"')
    parser.add_argument('--priority-id', type=str, default=None,
                        help='Priority ID for new bug. Defaults to copying the priority from the original bug. Not every priority is supported by each project.'
                             'When in doubt choose 8 for priority "None".')
    parser.add_argument('--undo', help='Undo the split; deletes the split issue if it exists.', action='store_true')

    return parser.parse_args()


def print_priorities(buf, priorities: Iterable[Priority]):
    for priority in priorities:
        buf.write(f'{priority.id}: {priority.name}\n')


def main(args):
    set_aws_profile()

    print('connecting to jira')
    jira_server = connect_to_jira()

    issue = jira_server.issue(args.issue_key)
    # link_types = jira_server.issue_link_types()

    project = jira_server.project(args.project_key.upper())

    # Select the issue type by ID
    try:
        issue_type = one(filter(lambda x: x.name.lower() == args.issue_type.lower(), project.issueTypes))
    except ValueError:
        stderr.write(f'project {args.project_key.upper()} has no issue type with name "{args.issue_type.lower()}" (case insensitive)\n')
        stderr.flush()
        return exit(1)  # return is to tell linters that branch terminates

    # Set priority. Default to the original issue's priority, otherwise select the priority by ID.
    priorities = jira_server.priorities()
    try:
        if args.priority_id is None:
            priority = issue.fields.priority
        else:
            priority = one(filter(lambda x: x.id == args.priority_id, priorities))
    except ValueError:
        stderr.write(f'invalid priority ID {args.priority_id}; choose from:\n')
        print_priorities(stderr, priorities)
        stderr.flush()
        return exit(1)  # return is to tell linters that branch terminates

    if not args.undo:
        split_issue(jira_server, issue, project, issue_type, priority)
    else:
        for link in issue.fields.issuelinks:
            if link.type.name == 'Issue split':
                _split_issue = link.outwardIssue.key

                print('found', link.type.name, _split_issue)

                def _deletion_condition(_issue):
                    return (_issue.fields.reporter.key == 'security.automation'
                            and _issue.fields.summary == issue.fields.summary)

                if delete_issue(jira_server, _split_issue, _deletion_condition):
                    print('deleted issue')


if __name__ == '__main__':
    main(get_cli_args())
