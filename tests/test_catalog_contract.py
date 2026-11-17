"""Subclass CatalogRepositoryContract and unittest.TestCase; provide open_repository().

Each test gets a fresh logical store. Repeated calls to the zero-argument callable
open independent repository instances against that same store, including on threads.
"""
from tests.fixtures.catalog_examples import LAB, Caller, catalog, source


class CatalogRepositoryContract:
    def setUp(self):
        super().setUp()
        self.repo = self.open_repository()
        self.curator = Caller()

    def test_reopen_catalog_and_source(self):
        manual = self.repo.save("source", LAB, "manual", source(), expected_revision=0, principal=self.curator)
        draft = self.repo.save("catalog", LAB, "uvvis", catalog(manual.pin.revision_id),
                               expected_revision=0, principal=self.curator)
        reopened = self.open_repository()
        self.assertEqual(reopened.get("source", LAB, "manual", principal=self.curator), manual)
        self.assertEqual(reopened.get("catalog", LAB, "uvvis", principal=self.curator), draft)
        self.assertEqual(draft.state, "draft")
