import pytest

from app.servicenow.instance import EXAMPLE_CONFIG_PATH, load_instance_config
from app.servicenow.mock import MockServiceNowClient


@pytest.fixture
def instance_config():
    return load_instance_config(EXAMPLE_CONFIG_PATH)


@pytest.fixture
def mock_client(instance_config):
    return MockServiceNowClient(instance_config)
