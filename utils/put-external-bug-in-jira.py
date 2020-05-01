"""
When in doubt, just run this script. It will create a json file for you to fill out. Note that you need bugdex installed.
"""

from __future__ import annotations
import json
from pathlib import Path
from types import ModuleType
from typing import Mapping, Any, Iterator

import attr
from jira import JIRAError

from sys import stderr

import bugdex.environment_tools
from bugdex.jira_tools import (
    connect_to_jira,
    deep_create_jira_bug,
    JiraBug,
)
from bugdex.core import deep_delete_source_specific_bug
from bugdex.vendor_to_jira import update_external_bug_to_jira

from sys import modules

if not (cache := modules.get('cache')):
    cache = ModuleType('cache')
    cache.jira_server = None
    modules['cache'] = cache


def get_jira_server():
    if cache.jira_server:
        return cache.jira_server
    else:
        print('connecting to jira server')
        cache.jira_server = connect_to_jira()
        return cache.jira_server


def alt_description() -> str:
    try:
        return Path('description.txt').read_text()
    except FileNotFoundError:
        return 'FILL ME IN'


@attr.s(auto_attribs=True, frozen=True)
class AttrMetadata(Mapping):
    include_when_serializing: bool = True

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __iter__(self) -> Iterator:
        return iter(attr.asdict(self))

    def __len__(self) -> int:
        return len(attr.asdict(self))


@attr.s(auto_attribs=True)
class Config:
    path: Path = attr.ib(metadata=AttrMetadata(include_when_serializing=False))

    ensure_dead: bool = False  # whether to delete if it exists
    summary: str = 'FILL ME IN'
    description: str = attr.ib(factory=alt_description)
    key: str = None
    external_url: str = 'unknown'
    source: str = None
    jira_bug: JiraBug = attr.ib(default=None, metadata=AttrMetadata(include_when_serializing=False))

    @classmethod
    def from_file(cls, path: Path) -> Config:
        try:
            config = Config(path=path, **json.loads(path.read_text()))
        except FileNotFoundError:
            print(f'{path} does not exist', file=stderr, flush=True)
            config = Config(path=path)
            config.dump()

        if jira_key := config.key:
            print('getting bug')

            # TODO:
            # - should get the bug from in DynamoDB.
            # - should check the JIRAError to make sure it is a "not exist" error

            try:
                config.jira_bug = JiraBug.from_raw_issue(get_jira_server().issue(jira_key))
            except JIRAError:
                pass
        elif not config.ensure_dead:
            print('creating bug')
            config.jira_bug = deep_create_jira_bug(jira_server=get_jira_server())
            jira_key = config.jira_bug.key
            config.key = jira_key

        config.dump()
        return config

    def dump(self, output_file: Path = None, /) -> None:
        output_file = output_file or self.path

        if not output_file:
            raise ValueError("no file to dump to")

        encoded = attr.asdict(self)
        for field in attr.fields(Config):
            AttrMetadata(field.metadata)
            if not AttrMetadata(**field.metadata).include_when_serializing:
                del encoded[field.name]

        output_file.write_text(json.dumps(encoded, indent=4))


def delete_bug(jira_bug: JiraBug, jira_server):
    print('deleting bug from jira')
    jira_bug.to_raw_issue(jira_server).delete()

    print('deleting bug from bugdex')
    deep_delete_source_specific_bug(jira_bug)


def update_external_bug_to_jira_from_bug_file(bug_file: Path):
    config = Config.from_file(bug_file)

    if config.ensure_dead:
        if config.jira_bug:
            delete_bug(config.jira_bug, get_jira_server())
        else:
            print('already dead')
    else:
        update_external_bug_to_jira(
            get_jira_server(),
            config.jira_bug,
            summary=config.summary,
            description=config.description,
            external_url=config.external_url,
            source=config.source
        )


if __name__ == '__main__':
    bugdex.environment_tools.set_aws_profile()
    update_external_bug_to_jira_from_bug_file(Path('bug.json'))
