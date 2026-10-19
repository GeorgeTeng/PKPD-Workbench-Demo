"""Keep pure unit tests collectible while EDA-dependent integration is deferred."""
import pytest


@pytest.fixture
def approval():
    pytest.skip('Requires retired EDA outputs; EDA is explicitly disabled.')
