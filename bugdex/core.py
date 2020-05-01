from __future__ import annotations
from typing import Optional, Iterable, TypeVar
from uuid import uuid4
import warnings

import more_itertools
import pynamodb.models
import toolz
from pynamodb.attributes import UnicodeAttribute, UnicodeSetAttribute
from pynamodb.connection import Connection
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.indexes import GlobalSecondaryIndex, KeysOnlyProjection, IncludeProjection, AllProjection
from pynamodb.transactions import TransactWrite, TransactGet

import logging

logger = logging.getLogger(__name__)

first = toolz.excepts(StopIteration, toolz.first)

T = TypeVar('T')


class CanonicalBug(pynamodb.models.Model):
    """Dynamo DB model for Canonical Bugs

    Disambiguated bug representation. There
    may be multiple representations of the same bug,
    but there should eventually be only one canonical bug for each real bug.
    The canonical bug is like the master branch in git.

    """

    uuid = UnicodeAttribute(hash_key=True)
    other_representations = UnicodeSetAttribute(null=True)
    former_canonical_representations = UnicodeSetAttribute(null=True)

    table_parameter_name = "/tables/bugdex/canonical_bugs"

    class Meta:
        table_name = "bugdex_canonical_bugs_v1"
        region = "us-west-2"

    def merge(self, another_representation: CanonicalBug):
        if another_representation.uuid == self.uuid:
            return

        for uuid in another_representation.other_representations:
            for universal_bug in UniversalBug.query(uuid):
                universal_bug.update(actions=[UniversalBug.canonical_bug.set(self.uuid)])

        if another_representation.other_representations:
            self.update(
                actions=[CanonicalBug.other_representations.add(another_representation.other_representations)]
            )

        another_representation.die(self)

    @classmethod
    def from_source_specific_bug(cls, source_specific_bug) -> CanonicalBug:
        for canonical_bug in CanonicalBug.query(UniversalBug.from_source_specific_bug(source_specific_bug).canonical_bug):
            return canonical_bug
        else:
            raise ValueError(f'{source_specific_bug} has no associated canonical bug')

    def die(self, replacement: Optional[CanonicalBug]):
        """
        Move to dead bugs table

        :param replacement: the uuid of the canonical bug that replaces this bug
        :return: None
        """

        if replacement is not None:
            actions = [
                CanonicalBug.former_canonical_representations.add({replacement.uuid}.union(self.former_canonical_representations or ()))
            ]
            if self.other_representations:
                actions.append(CanonicalBug.other_representations.add(self.other_representations))

            replacement.update(actions=actions)

        FormerCanonicalBug(uuid=self.uuid, replacement=replacement.uuid).save()
        self.delete()

    def garbage_collect(self):
        for other_repr in self.other_representations:
            universal_bug: UniversalBug = first(UniversalBug.query(other_repr))
            if universal_bug is None:
                self.die(None)
            elif universal_bug.canonical_bug != self.uuid:
                self.die(first(CanonicalBug.query(universal_bug.canonical_bug)))

    @classmethod
    def garbage_collect_all(cls):
        for bug in cls.scan():
            bug.garbage_collect()


class FormerCanonicalBug(pynamodb.models.Model):
    """Where canonical bugs go when they die"""

    uuid = UnicodeAttribute(hash_key=True)
    replacement = UnicodeAttribute(null=True)

    table_parameter_name = "/tables/bugdex/former_canonical_bugs"

    class Meta:
        table_name = "bugdex_former_canonical_bugs_v1"
        region = "us-west-2"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE


class SourceSpecificIndex(GlobalSecondaryIndex):
    """
    This class represents a global secondary index
    """

    class Meta:
        index_name = 'source_specific_id-source-index'
        projection = IncludeProjection(['universal_id', 'canonical_bug'])
        billing_mode = PAY_PER_REQUEST_BILLING_MODE

    source_specific_id = UnicodeAttribute(hash_key=True)
    source = UnicodeAttribute(range_key=True)


class CanonicalBugIndex(GlobalSecondaryIndex):
    """
    This class represents a global secondary index
    """

    class Meta:
        index_name = 'canonical_bug-index'
        projection = AllProjection()
        billing_mode = PAY_PER_REQUEST_BILLING_MODE

    canonical_bug = UnicodeAttribute(hash_key=True)


class UniversalBug(pynamodb.models.Model):
    """Dynamo DB model for Index of all bugs

    :attr universal_id: for an ideal bug, the universal_id is equal to the type_specific_id. Otherwise it is just some unique UUID.
    :attr ideal_bug: the ideal bug ID that is associated with this bug. For an ideal bug, the ideal_bug is itself or another
        ideal bug. The latter case can happen if in the case of duplicate ideal bugs, and the redundant bug has not been cleaned up.
    :attr source: source of bug, in all lower case. E.g. "jira".
    :attr source_specific_id: the id specific to the type of bug. E.g., for Jira, this is the Jira id.

    """

    universal_id = UnicodeAttribute(hash_key=True)
    canonical_bug = UnicodeAttribute()
    source = UnicodeAttribute()
    source_specific_id = UnicodeAttribute()
    source_specific_index = SourceSpecificIndex()
    canonical_bug_index = CanonicalBugIndex()

    table_parameter_name = "/tables/bugdex/universal_bug_index"

    class Meta:
        table_name = "bugdex_universal_bug_index_v1"
        region = "us-west-2"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE

    @classmethod
    def propose(cls, universal_id, source, source_specific_id, canonical_bug=None) -> UniversalBug:
        """
        Creates universal bug as proposed if it does not exist, then returns it. Does not
        overwrite.
        """
        if universal_bug := more_itertools.only(cls.query(universal_id)):
            # TODO: validate source and source_specific_id
            canonical_bug: CanonicalBug = first(CanonicalBug.query(universal_bug.canonical_bug))
            if universal_bug.universal_id not in (canonical_bug.other_representations or ()):
                canonical_bug.update(actions=[CanonicalBug.other_representations.add({universal_bug.universal_id})])
            return universal_bug
        else:
            canonical_bug_uuid = str(canonical_bug or uuid4()).lower()

            CanonicalBug(
                uuid=canonical_bug_uuid,
                other_representations=[universal_id],
            ).save()

            universal_bug = cls(
                universal_id=universal_id,
                canonical_bug=canonical_bug_uuid,
                source=source,
                source_specific_id=source_specific_id,
            )

            universal_bug.save()

            return universal_bug

    def migrate_v1_1_6(self):
        actions = [
            # UniversalBug.source_specific_id.set(self.source_specific_id.split(':')[-1]),
            # UniversalBug.source_specific_index.remove(),
        ]
        self.update(actions)

    @classmethod
    def from_source_specific_bug(cls, source_specific_bug):
        for universal_bug in cls.query(source_specific_bug.universal_id):
            return universal_bug
        raise ValueError(f'{source_specific_bug} has no associated universal bug')

    @classmethod
    def from_source_specific_index(cls, source_specific_id, /, *, source):
        return first(cls.source_specific_index.query(source_specific_id, cls.source == source))

    @classmethod
    def from_non_canonical_bug(cls, non_canonical_bug):
        if isinstance(non_canonical_bug, UniversalBug):
            return non_canonical_bug
        elif isinstance(non_canonical_bug, CanonicalBug):
            raise TypeError(f"{non_canonical_bug} should not be a CanonicalBug")
        else:
            return UniversalBug.from_source_specific_bug(non_canonical_bug)


def related_bugs(non_canonical_bug) -> Iterable[UniversalBug]:
    ub = UniversalBug.from_non_canonical_bug(non_canonical_bug)
    return UniversalBug.canonical_bug_index.query(
        ub.canonical_bug,
        filter_condition=UniversalBug.universal_id != ub.universal_id,
    )


def deep_delete_source_specific_bug(bug):
    """Delete the source specific bug, its universal bug, and clean up canonical bug / links

    Note: does not delete the bug data in the external source, e.g. Jira bugs
    will not be deleted from the Jira server
    """

    canonical_bug = CanonicalBug.from_source_specific_bug(bug)
    universal_bug = UniversalBug.from_source_specific_bug(bug)
    delete_canonical_bug = len(canonical_bug.other_representations) == 0

    universal_id = bug.universal_id

    bug.delete()
    universal_bug.delete()
    if delete_canonical_bug:
        canonical_bug.delete()
    else:
        canonical_bug.update(actions=[CanonicalBug.other_representations.delete([universal_id])])
