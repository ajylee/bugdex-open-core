import textwrap
from typing import Optional
from warnings import warn

from jira import JIRA

from .jira_tools import JiraBug, BugdexJiraFields, update_bug


def update_external_bug_to_jira(jira_server: JIRA, jira_bug: JiraBug, summary: str, description: str, source: Optional[str], external_url: str):
    """Call the Jira server to update an existing JiraBug representing a bug from vendor
    """

    metadata_section = textwrap.dedent(f"""
    {description}


    h2. Bug Metadata

    External URL: {external_url}
    """)

    labels = {'Bugdex'}
    if source is None:
        pass
    elif source.lower() == 'vendor1':
        labels.add('vendor1')
    elif source.lower() == 'vendor2':
        labels.add('vendor2')
    elif source.lower() == 'vendor3':
        labels.add('vendor3')
    else:
        warn(f'source {source} not recognized')

    jira_fields = BugdexJiraFields(
        summary=f'[bugdex] {summary}',
        description=metadata_section,
        labels=labels,
        components=BugdexJiraFields.recommended_components,
    )

    print('updating bug')
    update_bug(jira_server, jira_bug, fields=jira_fields)
