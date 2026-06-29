"""Support for services."""

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .aiogree.device import GreeDevice
from .const import ATTR_SVC_PROPS, DOMAIN
from .coordinator import GreeConfigEntry, GreeCoordinator

_LOGGER = logging.getLogger(__name__)

SVC_BASE_SCHEMA = {
    vol.Required(ATTR_DEVICE_ID): cv.string,
}

SVC_GET_PROPS_ALL = "get_prop_values_all"
SVC_GET_PROPS_ALL_SCHEMA = vol.Schema(SVC_BASE_SCHEMA)

SVC_GET_PROPS = "get_prop_values"
SVC_GET_PROPS_SCHEMA = vol.Schema(
    SVC_GET_PROPS_ALL_SCHEMA.extend(
        {
            vol.Required(ATTR_SVC_PROPS): vol.All([cv.string]),
        }
    )
)


@callback
def async_get_device_from_service_call(
    call: ServiceCall,
) -> GreeDevice:
    """Get the config entry related to a service call (by device ID)."""
    device_registry = dr.async_get(call.hass)
    device_id = call.data[ATTR_DEVICE_ID]

    if (device_entry := device_registry.async_get(device_id)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
        )

    # Find MAC address for this device (from identifiers)
    mac: str | None = next(
        (
            identifier
            for domain, identifier in device_entry.identifiers
            if domain == DOMAIN
        ),
        None,
    )

    if mac is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
        )

    config_entry: GreeConfigEntry | None = None
    for entry_id in device_entry.config_entries:
        entry = call.hass.config_entries.async_get_entry(entry_id)

        if TYPE_CHECKING:
            assert entry

        if entry.domain != DOMAIN:
            continue
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
            )

        config_entry = entry

    if not config_entry:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="config_entry_not_found",
        )

    runtime_data: GreeCoordinator | None = config_entry.runtime_data.get(mac, None)

    if not runtime_data:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_config_data",
        )

    return runtime_data.device


async def async_get_prop_values_all(call: ServiceCall) -> ServiceResponse:
    """Handle the get_prop_values_all service call."""

    _LOGGER.debug("Service called: get_prop_values_all")
    device: GreeDevice = async_get_device_from_service_call(call)
    state, missing = await device.query_props_all(error_as_missing=True)

    result: dict[str, Any] = {}
    result["states"] = state
    result["missing"] = missing

    return result


async def async_get_prop_values(call: ServiceCall) -> ServiceResponse:
    """Handle the get_prop_values service call."""

    _LOGGER.debug("Service called: get_prop_values")

    props = call.data[ATTR_SVC_PROPS]

    device: GreeDevice = async_get_device_from_service_call(call)
    state, missing = await device.query_props(props=props, error_as_missing=True)

    result: dict[str, Any] = {}
    result["states"] = state
    result["missing"] = missing

    return result


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Set up the services for Shelly integration."""
    for service, method, schema, response in (
        (
            SVC_GET_PROPS_ALL,
            async_get_prop_values_all,
            SVC_GET_PROPS_ALL_SCHEMA,
            SupportsResponse.ONLY,
        ),
        (
            SVC_GET_PROPS,
            async_get_prop_values,
            SVC_GET_PROPS_SCHEMA,
            SupportsResponse.ONLY,
        ),
    ):
        hass.services.async_register(
            DOMAIN,
            service,
            method,
            schema=schema,
            supports_response=response,
        )
