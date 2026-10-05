"""The ledger of what an update did to a person's files, so the review can say it."""

from __future__ import annotations

import unittest

from common import migration_ledger
from tests.support.library import TempTree


class LedgerTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.root / "migrations.json"

    def test_nothing_is_recorded_on_a_fresh_file(self) -> None:
        self.assertEqual(migration_ledger.entries("", self.path), [])

    def test_an_entry_keeps_its_name_version_and_count_across_a_reload(self) -> None:
        migration_ledger.record("order_direction", "v3.1.0", 4, self.path)

        [entry] = migration_ledger.entries("", self.path)

        self.assertEqual((entry.name, entry.version, entry.count),
                         ("order_direction", "v3.1.0", 4))

    def test_the_same_name_under_one_version_adds_its_count(self) -> None:
        migration_ledger.record("info_upgrade", "v3.1.0", 4, self.path)
        migration_ledger.record("info_upgrade", "v3.1.0", 2, self.path)

        [entry] = migration_ledger.entries("", self.path)

        self.assertEqual(entry.count, 6)

    def test_the_same_name_under_a_later_version_is_its_own_entry(self) -> None:
        migration_ledger.record("info_upgrade", "v3.1.0", 4, self.path)
        migration_ledger.record("info_upgrade", "v3.2.0", 9, self.path)

        self.assertEqual([(e.version, e.count) for e in migration_ledger.entries("", self.path)],
                         [("v3.1.0", 4), ("v3.2.0", 9)])

    def test_a_file_that_cannot_be_read_is_not_replaced(self) -> None:
        migration_ledger.record("old", "v3.0.0", 1, self.path)
        self.path.chmod(0)
        try:
            migration_ledger.record("new", "v3.1.0", 2, self.path)
        finally:
            self.path.chmod(0o600)

        self.assertEqual([e.name for e in migration_ledger.entries("", self.path)], ["old"])

    def test_only_what_ran_after_the_last_version_is_listed(self) -> None:
        migration_ledger.record("old", "v3.0.0", 1, self.path)
        migration_ledger.record("new", "v3.1.0", 2, self.path)

        self.assertEqual([e.name for e in migration_ledger.entries("v3.0.0", self.path)],
                         ["new"])

    def test_nothing_recorded_as_the_last_version_lists_every_release_entry(self) -> None:
        migration_ledger.record("old", "v3.0.0", 1, self.path)
        migration_ledger.record("new", "v3.1.0", 2, self.path)

        self.assertEqual([e.name for e in migration_ledger.entries("", self.path)],
                         ["old", "new"])

    def test_an_entry_from_a_build_that_is_not_a_release_is_never_listed(self) -> None:
        migration_ledger.record("from_source", "dev-local", 3, self.path)

        self.assertEqual(migration_ledger.entries("", self.path), [])

    def test_a_file_that_cannot_be_read_lists_nothing_and_records_again(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(migration_ledger.entries("", self.path), [])

        migration_ledger.record("order_direction", "v3.1.0", 4, self.path)

        self.assertEqual(len(migration_ledger.entries("", self.path)), 1)


if __name__ == "__main__":
    unittest.main()
