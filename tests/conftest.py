from __future__ import annotations

import pytest

from ma_due_diligence.domain import DiligenceFixtureSet
from ma_due_diligence.fixtures import build_synthetic_fixture


@pytest.fixture
def diligence_fixture() -> DiligenceFixtureSet:
    return build_synthetic_fixture()
