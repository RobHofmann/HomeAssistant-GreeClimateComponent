
from custom_components.gree.climate import GreeClimate
from homeassistant.components.climate import HVACMode

# Fixtures (mock_hass, gree_climate_device) are automatically discovered from conftest.py

# --- Property Tests ---

async def test_properties_before_update(gree_climate_device: GreeClimate):
    """Test default property values before the first update."""
    # Check properties that have default values before any update is run
    assert gree_climate_device.hvac_mode == HVACMode.OFF # Default seems to be OFF based on __init__
    assert gree_climate_device.fan_mode is None # Or expected default
    assert gree_climate_device.swing_mode is None # Or expected default
    assert gree_climate_device.preset_mode is None # Or expected default
    assert gree_climate_device.target_temperature is None # Or expected default
    assert gree_climate_device.current_temperature is None # Or expected default
    assert gree_climate_device.available is False # Should be unavailable before first successful update
    # Add more assertions for other default properties
    pass # Placeholder for more detailed assertions 