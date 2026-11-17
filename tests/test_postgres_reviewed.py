"""Run domain owners' shared suites with PostgreSQL when their WOs are composed."""
from importlib.util import find_spec
from unittest import TestCase, skipUnless

from tests.test_postgres_repositories import BASE_DSN, isolated_database


if find_spec("factory.catalog_domain"):
    from tests.test_catalog_contract import CatalogRepositoryContract

    @skipUnless(BASE_DSN, "use tests/fixtures/postgres/run.sh")
    class HostedCatalogContract(CatalogRepositoryContract, TestCase):
        def setUp(self):
            self.dsn = self.enterContext(isolated_database())
            super().setUp()

        def open_repository(self):
            from factory.postgres.catalog import PostgresCatalogRepository
            return PostgresCatalogRepository(self.dsn)
else:
    class HostedCatalogContract(TestCase):
        def test_catalog_contract(self):
            self.skipTest("requires WO-28's catalog domain and conformance suite")


@skipUnless(BASE_DSN, "use tests/fixtures/postgres/run.sh")
class HostedReviewedContracts(TestCase):
    @skipUnless(find_spec("factory.scientific_artifact_repository"), "requires WO-31's artifact domain")
    def test_scientific_artifact_contract(self):
        from factory.postgres.artifacts import PostgresScientificArtifactRepository
        from tests.fixtures.scientific_artifact_contract import check_repository
        with isolated_database() as dsn:
            check_repository(self, lambda principal: PostgresScientificArtifactRepository(dsn, principal))

    @skipUnless(find_spec("factory.runtime_work_order_domain"), "requires WO-37's runtime domain")
    def test_runtime_contract(self):
        from factory.postgres.runtime import PostgresRuntimeWorkOrderRepository
        from tests.test_runtime_work_order_contract import run_runtime_work_order_contract
        with isolated_database() as dsn:
            run_runtime_work_order_contract(lambda: PostgresRuntimeWorkOrderRepository(dsn))
