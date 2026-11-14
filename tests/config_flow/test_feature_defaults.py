"""Which device features are on when the user has not chosen them.

Auxiliary heat is opt-in: many units answer `AssHt` without having the heater,
so a new device starts without it and an entry without a saved features list
does not create the select.
"""

from unittest.mock import MagicMock

from custom_components.gree_custom.aiogree.api import DeviceType
from custom_components.gree_custom.config_schema import setup_device_options_schema
from custom_components.gree_custom.const import (
    CONF_DEVICE_OPTIONS,
    CONF_FEATURES,
    DEFAULT_SUPPORTED_FEATURES,
    GATTR_BEEPER,
    GATTR_FEAT_AUXILIARY_HEAT,
    OPT_IN_FEATURES,
)
from custom_components.gree_custom.platform_helpers import supported_descriptions
from custom_components.gree_custom.select import SELECT_TYPES
from homeassistant.core import HomeAssistant


def _unit_with_every_prop() -> MagicMock:
    """Return a unit that answers every property, as many units do for AssHt."""
    device = MagicMock()
    device.name = "Unit"
    device.device_type = DeviceType.AC_UNIT
    device.supports_property.return_value = True
    return device


def _features_field(schema) -> tuple[list[str], list[str]]:
    """Return the default and the offered options of the features field."""
    for key, value in schema.schema.items():
        if str(key.schema) == CONF_FEATURES:
            return key.default(), value.config["options"]
    raise AssertionError("no features field")


def test_auxiliary_heat_is_opt_in() -> None:
    """The feature is opt-in and not in the defaults for YAML and migrated entries."""
    assert GATTR_FEAT_AUXILIARY_HEAT in OPT_IN_FEATURES
    assert GATTR_FEAT_AUXILIARY_HEAT not in DEFAULT_SUPPORTED_FEATURES


async def test_new_device_form_leaves_auxiliary_heat_unticked(
    hass: HomeAssistant,
) -> None:
    """The form offers the feature, but does not tick it for a new device."""
    schema = setup_device_options_schema(hass, _unit_with_every_prop(), None)

    default, options = _features_field(schema)

    assert GATTR_FEAT_AUXILIARY_HEAT in options
    assert GATTR_FEAT_AUXILIARY_HEAT not in default
    assert GATTR_BEEPER in default


async def test_saved_features_keep_auxiliary_heat(hass: HomeAssistant) -> None:
    """A device that has the feature turned on keeps it in Edit device."""
    schema = setup_device_options_schema(
        hass,
        _unit_with_every_prop(),
        {CONF_FEATURES: [GATTR_BEEPER, GATTR_FEAT_AUXILIARY_HEAT]},
    )

    default, _ = _features_field(schema)

    assert default == [GATTR_BEEPER, GATTR_FEAT_AUXILIARY_HEAT]


def test_select_needs_the_feature_turned_on() -> None:
    """Without a saved features list the select is not created; with it, it is."""
    device = _unit_with_every_prop()

    def keys(device_config: dict) -> list[str]:
        return [
            d.key for d in supported_descriptions(SELECT_TYPES, device, device_config)
        ]

    assert GATTR_FEAT_AUXILIARY_HEAT not in keys({CONF_DEVICE_OPTIONS: {}})
    assert GATTR_FEAT_AUXILIARY_HEAT in keys(
        {CONF_DEVICE_OPTIONS: {CONF_FEATURES: [GATTR_FEAT_AUXILIARY_HEAT]}}
    )
