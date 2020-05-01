import bugdex.jira_tools
import bugdex.environment_tools
import bugdex.core
import bugdex

bugdex.environment_tools.set_aws_profile()

for model in [
    bugdex.jira_tools.JiraBug,
    bugdex.CanonicalBug,
    bugdex.UniversalBug,
    bugdex.core.FormerCanonicalBug,
]:
    if not model.exists():
        model.create_table(billing_mode='PAY_PER_REQUEST')
