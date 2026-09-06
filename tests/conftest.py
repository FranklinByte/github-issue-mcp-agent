from pathlib import Path

import pytest

from issue_agent.config import Settings
from issue_agent.storage import Store


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, retry_delay=0)


@pytest.fixture
def store(settings: Settings) -> Store:
    return Store(settings.db_path)
