import os
from pathlib import Path

import pytest
from app.models import ProductFamily
from app.public_client import PublicClient


@pytest.mark.network
@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="Opt-in public network test: RUN_NETWORK_TESTS=1",
)
def test_public_time(tmp_path: Path) -> None:
    with PublicClient(ProductFamily.USD_M_FUTURES, tmp_path) as client:
        result = client.get("/fapi/v1/time")
    assert result.ok and isinstance(result.data["serverTime"], int)
