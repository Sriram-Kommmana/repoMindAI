import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

TEST_REPO = os.path.join(ROOT, "test_repo")


def _neo4j_reachable() -> bool:
    try:
        from graph.loader import _get_driver

        driver = _get_driver()
        try:
            driver.verify_connectivity()
            return True
        finally:
            driver.close()
    except Exception:
        return False


@pytest.fixture(scope="session")
def neo4j():
    """Tests using this fixture write to the shared graph (loading wipes it),
    exactly as an analysis would; they skip when the database is unreachable."""
    if not _neo4j_reachable():
        pytest.skip("Neo4j is unreachable (check the Aura instance is running and .env is set)")
    return True
