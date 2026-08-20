"""Helpers for the Gree integration."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import logging
from typing import TypeVar

from homeassistant.const import CONF_MAC
from homeassistant.helpers.entity_platform import Any

from .aiogree.api import GreeProp
from .aiogree.device import GreeDevice
from .const import (
    CONF_ADVANCED,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_FEATURES,
    CONF_RESTORE_STATES,
    CONF_TO_PROP_FEATURE_MAP,
    DEFAULT_DISABLE_AVAILABLE_CHECK,
    DEFAULT_RESTORE_STATES,
    DEFAULT_SUPPORTED_FEATURES,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


T = TypeVar("T", bound=GreeEntityDescription)


@dataclass(slots=True)
class GreePlatformContext:
    """Provides the context for platform entity creation."""

    device_config: dict[str, Any]
    coordinator: GreeCoordinator
    restore_state: bool
    check_availability: bool


def iter_platform_context(
    entry: GreeConfigEntry,
) -> Iterator[GreePlatformContext]:
    """Yield context for every configured device."""

    check_availability = not entry.data[CONF_ADVANCED].get(
        CONF_DISABLE_AVAILABLE_CHECK,
        DEFAULT_DISABLE_AVAILABLE_CHECK,
    )

    for device_config in entry.data.get(CONF_DEVICES, []):
        mac = device_config.get(CONF_MAC, "")

        coordinator = entry.runtime_data.get(mac)
        if coordinator is None:
            _LOGGER.error(
                "No coordinator found for device '%s'",
                mac,
            )
            continue

        yield GreePlatformContext(
            device_config=device_config,
            coordinator=coordinator,
            restore_state=device_config.get(
                CONF_RESTORE_STATES,
                DEFAULT_RESTORE_STATES,
            ),
            check_availability=check_availability,
        )


def supported_descriptions(
    descriptions: Sequence[T],
    device: GreeDevice,
    device_config: dict[str, Any] | None = None,
) -> list[T]:
    """Return the supported feature descriptions for a device.

    Args:
        descriptions: `GreeEntityDescription` list of entity descriptions.
        device: The device to check for property support,
        device_config: Device configuration. If omitted, all ``descriptions`` are used.
    """
    configured_features: list[str] = (
        set(device_config.get(CONF_FEATURES, DEFAULT_SUPPORTED_FEATURES))
        if device_config is not None
        else None
    )

    supported: list[T] = []

    for description in descriptions:
        feature = entity_feature_key(description)

        if (
            configured_features is not None
            and not description.auto_device_support
            and feature not in configured_features
        ):
            continue

        props: list[GreeProp] = CONF_TO_PROP_FEATURE_MAP.get(feature)
        if props and any(device.supports_property(p) for p in props):
            supported.append(description)

    return supported


def entity_feature_key(entity_description: T) -> str:
    """Returns the correct feature key for an entity description."""
    # This is needed because the description dataclasses don't allow methods/properties
    return entity_description.feature_key_override or entity_description.key
