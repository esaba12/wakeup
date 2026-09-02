from __future__ import annotations

import pytest

from openrestore.core.clock import FakeClock


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()
