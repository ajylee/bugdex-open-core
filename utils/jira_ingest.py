from bugdex.jira_tools import connect_to_jira, JiraBug
from bugdex import environment_tools

environment_tools.set_aws_profile()

jira_server = connect_to_jira()
for bug in JiraBug.ingest(jira_server):
    print('ingested', bug.key)
