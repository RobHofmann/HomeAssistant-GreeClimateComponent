import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from homeassistant.core import HomeAssistant
from custom_components.gree.climate import GreeClimate
from homeassistant.components.climate import HVACMode
from homeassistant.components.climate.const import (
    HVACAction,
    ClimateEntityFeature,
    ATTR_HVAC_MODE,
    FAN_AUTO, FAN_HIGH, FAN_LOW, FAN_MEDIUM,
    SWING_BOTH, SWING_HORIZONTAL, SWING_OFF, SWING_VERTICAL
)
# Add other necessary imports like HVACMode, specific temperatures, etc.

# Fixtures (mock_hass, gree_climate_device) are automatically discovered from conftest.py

# --- Command Method Tests ---

# Example: Patching SendStateToAc which seems common for commands
@patch("custom_components.gree.climate.GreeClimate.turn_on")
async def test_async_turn_on(mock_turn_on, gree_climate_device: GreeClimate):
    """Test turning the device on."""
    # Ensure device starts 'off' (or set initial state if needed)
    # Setting internal state might be less brittle than relying on _acOptions
    gree_climate_device._hvac_mode = HVACMode.OFF

    await gree_climate_device.async_turn_on()

    # Assert that the synchronous turn_on method was called (via executor)
    mock_turn_on.assert_called_once()

@patch("custom_components.gree.climate.GreeClimate.turn_off")
async def test_async_turn_off(mock_turn_off, gree_climate_device: GreeClimate):
    """Test turning the device off."""
    # Ensure device starts 'on' (or set initial state if needed)
    # Setting internal state might be less brittle
    gree_climate_device._hvac_mode = HVACMode.HEAT_COOL 
    # gree_climate_device._acOptions["Pow"] = 1 # Also set this if turn_off uses it directly
    
    await gree_climate_device.async_turn_off()
    
    mock_turn_off.assert_called_once()
    # TODO: Verify the exact expected call (e.g., with Pow=0)

@patch("custom_components.gree.climate.GreeClimate.set_temperature") # Patch synchronous method
async def test_async_set_temperature(mock_set_temperature, gree_climate_device: GreeClimate):
    """Test setting the target temperature."""
    test_temp = 24.0
    
    # Call the async service method
    await gree_climate_device.async_set_temperature(temperature=test_temp)
    
    # Assert the synchronous method was called via executor
    # Assuming signature is similar: set_temperature(self, *, temperature: float | None = None, ...)
    mock_set_temperature.assert_called_once_with(temperature=test_temp)

@pytest.mark.asyncio
@patch("custom_components.gree.climate.GreeClimate.set_hvac_mode")
async def test_async_set_hvac_mode(mock_set_hvac_mode, gree_climate_device):
    """Test setting HVAC mode calls the synchronous method."""
    await gree_climate_device.async_set_hvac_mode(hvac_mode=HVACMode.COOL)
    mock_set_hvac_mode.assert_called_once_with(HVACMode.COOL)

@pytest.mark.asyncio
@patch("custom_components.gree.climate.GreeClimate.set_fan_mode")
async def test_async_set_fan_mode(mock_set_fan_mode, gree_climate_device: GreeClimate):
    """Test setting the fan mode calls the synchronous method."""
    await gree_climate_device.async_set_fan_mode(fan_mode=FAN_MEDIUM)
    mock_set_fan_mode.assert_called_once_with(FAN_MEDIUM)

@pytest.mark.asyncio
@patch("custom_components.gree.climate.GreeClimate.set_swing_mode")
async def test_async_set_swing_mode(mock_set_swing_mode, gree_climate_device: GreeClimate):
    """Test setting the swing mode calls the synchronous method."""
    await gree_climate_device.async_set_swing_mode(swing_mode=SWING_VERTICAL)
    mock_set_swing_mode.assert_called_once_with(SWING_VERTICAL)

# Add more tests for other command methods as needed 