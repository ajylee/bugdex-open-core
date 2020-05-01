from os import uname, environ
import boto3
from zsec_aws_tools.iam import session_with_aliasing_workaround

not_amzn_env = ('amzn' not in uname().release or 'Darwin' in uname().sysname) and not environ.get('BUGDEX_AGENT_TYPE') == 'CODEBUILD'


def set_aws_profile():
    if not_amzn_env and not environ.get('AWS_PROFILE'):
        resolved_profile_name, _region_name = resolve_profile_alias(profile_name='bug-management')
        environ['AWS_PROFILE'] = resolved_profile_name


def get_session() -> boto3.Session:
    if not_amzn_env and not environ.get('AWS_PROFILE'):
        profile_name = 'bug-management'
    else:
        profile_name = environ.get('AWS_PROFILE')

    resolved_profile_name, region_name = resolve_profile_alias(profile_name=profile_name)
    return boto3.Session(profile_name=resolved_profile_name, region_name=region_name)


def resolve_profile_alias(profile_name=None, region_name=None):
    """Wrapper around boto3.Session that behaves better with `~/.aws/config`

    Will follow the source_profile of `profile_name` in `~/.aws/config` if found
    and the only keys it has are `source_profile` and `region`. More complicated
    configurations are not supported for the workaround behavior,
    and this function reverts to the original behavior of `boto3.Session`.

    If `profile_name` is not found in `~/.aws/config`, this function reverts to
    the original behavior of `boto3.Session`.

    Note that this function is necessary because `boto3.Session` will
    ignore aliases for some complicated configurations of `source_profile`.

    """

    import configparser
    from pathlib import Path

    config = configparser.ConfigParser()
    config.read(Path('~/.aws/config').expanduser())

    cnt = 0
    while cnt < 5:
        cnt += 1
        if profile_name:
            try:
                profile_config = config['profile ' + profile_name]
            except KeyError:
                break
            else:
                if set(profile_config.keys()) <= {'source_profile', 'region'}:
                    new_profile_name = profile_config.get('source_profile', profile_name)
                    if region_name is None:
                        region_name = profile_config.get('region', region_name)
                    if new_profile_name == profile_name:
                        break
                    else:
                        profile_name = new_profile_name
                else:
                    break

        else:
            break

    return profile_name, region_name
