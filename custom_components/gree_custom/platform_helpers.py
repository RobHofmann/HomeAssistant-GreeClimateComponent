"""Helpers for the Gree integration."""

from collections.abc import Sequence
import logging
from typing import Any, TypeVar

from config.custom_components.gree_custom.const import CONF_DEVICE_OPTIONS

from .aiogree.api import GreeProp
from .aiogree.device import GreeDevice
from .const import CONF_FEATURES, CONF_TO_PROP_FEATURE_MAP, DEFAULT_SUPPORTED_FEATURES
from .entity import GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


T = TypeVar("T", bound=GreeEntityDescription)


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
    configured_features: list[str] | None = (
        device_config.get(CONF_DEVICE_OPTIONS, {}).get(
            CONF_FEATURES, DEFAULT_SUPPORTED_FEATURES
        )
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

        props: list[GreeProp] = CONF_TO_PROP_FEATURE_MAP.get(feature, [])
        if props and any(device.supports_property(p) for p in props):
            supported.append(description)

    return supported


def entity_feature_key(entity_description: GreeEntityDescription) -> str:
    """Return the correct feature key for an entity description."""
    # This is needed because the description dataclasses don't allow methods/properties
    return entity_description.feature_key_override or entity_description.key
