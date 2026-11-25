"""Which device features are on when the user has not chosen them.

Auxiliary heat is opt-in: many units answer `AssHt` without having the heater,
so a new device starts without it and an entry without a saved features list
does not create the select.

UV Lamp is on by default, like Health: a unit without the lamp leaves
`UvcControl` out of its reply, so the switch is only created when the unit
answers the column (issue 585).
"""

from unittest.mock import MagicMock

from custom_components.gree_custom.aiogree.api import DeviceType, GreeProp
from custom_components.gree_custom.config_schema import setup_device_options_schema
from custom_components.gree_custom.const import (
    CONF_DEVICE_OPTIONS,
    CONF_FEATURES,
    DEFAULT_SUPPORTED_FEATURES,
    GATTR_BEEPER,
    GATTR_FEAT_AUXILIARY_HEAT,
    GATTR_FEAT_HUMIDITY,
    GATTR_FEAT_UV_LAMP,
    GATTR_TEMP_UNITS,
    OPT_IN_FEATURES,
)
from custom_components.gree_custom.platform_helpers import supported_descriptions
from custom_components.gree_custom.select import SELECT_TYPES, restores_state
from custom_components.gree_custom.switch import SWITCH_TYPES
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


def test_device_function_selects_follow_restore_states() -> None:
    """Humidity Control and Auxiliary Heat follow the option; units never restore."""
    by_key = {d.key: d for d in SELECT_TYPES}

    for key in (GATTR_FEAT_AUXILIARY_HEAT, GATTR_FEAT_HUMIDITY):
        assert restores_state(by_key[key], True)
        assert not restores_state(by_key[key], False)

    assert not restores_state(by_key[GATTR_TEMP_UNITS], True)


def test_uv_lamp_is_on_by_default() -> None:
    """The feature is on for a device without a saved features list."""
    assert GATTR_FEAT_UV_LAMP in DEFAULT_SUPPORTED_FEATURES
    assert GATTR_FEAT_UV_LAMP not in OPT_IN_FEATURES


async def test_new_device_form_ticks_uv_lamp_when_answered(hass: HomeAssistant) -> None:
    """The form offers and ticks the feature for a unit that answers UvcControl."""
    schema = setup_device_options_schema(hass, _unit_with_every_prop(), None)

    default, options = _features_field(schema)

    assert GATTR_FEAT_UV_LAMP in options
    assert GATTR_FEAT_UV_LAMP in default


async def test_new_device_form_hides_uv_lamp_when_not_answered(
    hass: HomeAssistant,
) -> None:
    """A unit that leaves UvcControl out is not offered the feature."""
    device = _unit_with_every_prop()
    device.supports_property.side_effect = lambda prop: (
        prop is not GreeProp.FEAT_UV_LAMP
    )
    schema = setup_device_options_schema(hass, device, None)

    default, options = _features_field(schema)

    assert GATTR_FEAT_UV_LAMP not in options
    assert GATTR_FEAT_UV_LAMP not in default
    assert GATTR_BEEPER in default


def test_uv_lamp_switch_needs_the_unit_to_answer_uvccontrol() -> None:
    """With the default features, the switch exists only when the column is answered."""
    default_config: dict = {CONF_DEVICE_OPTIONS: {}}

    def keys(device: MagicMock) -> list[str]:
        return [
            d.key for d in supported_descriptions(SWITCH_TYPES, device, default_config)
        ]

    with_lamp = _unit_with_every_prop()
    without_lamp = _unit_with_every_prop()
    without_lamp.supports_property.side_effect = lambda prop: (
        prop is not GreeProp.FEAT_UV_LAMP
    )

    assert GATTR_FEAT_UV_LAMP in keys(with_lamp)
    assert GATTR_FEAT_UV_LAMP not in keys(without_lamp)
