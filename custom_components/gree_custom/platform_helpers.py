"""Helpers for the Gree integration."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import logging
from typing import TypeVar

from homeassistant.const import CONF_MAC
from homeassistant.helpers.entity_platform import Any

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
    platform: str,
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
                "Cannot create Gree %s. No coordinator found for device '%s'",
                platform,
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


def supported_features(
    device_config: dict, coordinator: GreeCoordinator, subset: list[str] | None = None
) -> set[str]:
    """Extracts supported features from a device config and device support."""
    features: list[str] = device_config.get(
        CONF_FEATURES,
        DEFAULT_SUPPORTED_FEATURES,
    )

    if subset is not None:
        features = [feature for feature in features if feature in subset]

    supported: set[str] = set()

    for feature in features:
        prop = CONF_TO_PROP_FEATURE_MAP.get(feature)
        if prop and coordinator.device.supports_property(prop):
            supported.add(feature)

    return supported


def filter_descriptions(descriptions: Sequence[T], supported: set[str]) -> list[T]:
    """Filters a list of entity descriptions based on a supported features list."""
    return [d for d in descriptions if entity_feature_key(d) in supported]


def entity_feature_key(entity_description: T) -> str:
    """Returns the correct feature key for an entity description."""
    # This is needed because the description dataclasses don't allow methods/properties
    return entity_description.feature_key_override or entity_description.key
