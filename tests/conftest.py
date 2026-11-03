import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def raw_dir():
    return RAW


@pytest.fixture
def fixtures_dir():
    return FIXTURES


@pytest.fixture
def tmp_data(tmp_path):
    """Cópia editável do recorte pequeno dos CSVs (os originais nunca são tocados)."""
    dest = tmp_path / "data"
    shutil.copytree(FIXTURES, dest)
    return dest
