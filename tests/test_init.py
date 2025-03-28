import pytest
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from custom_components.gree.climate import GreeClimate

# Fixtures (mock_hass, gree_climate_device) are automatically discovered from conftest.py

# --- Initialization Tests ---

async def test_init_minimal_config(gree_climate_device: GreeClimate):
    """Test initialization with minimal configuration."""
    # Basic checks after fixture instantiation
    assert gree_climate_device is not None
    assert gree_climate_device.name == "Test Gree AC"
    # Add more assertions as needed for minimal init state
    pass # Placeholder for more detailed assertions

async def test_init_with_optional_entities(mock_hass: HomeAssistant):
    """Test initialization with optional entity IDs configured."""
    # Requires creating a device instance differently than the fixture
    # TODO: Implement this test, likely involves creating a GreeClimate instance
    #       directly here with specific entity IDs provided.
    pass 