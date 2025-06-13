"""Translation helper for Gree Climate component."""
import logging
import json
import os

_LOGGER = logging.getLogger(__name__)

# Translation keys for modes - these define the order and available modes
FAN_MODE_KEYS = ['auto', 'low', 'medium-low', 'medium', 'medium-high', 'high', 'turbo', 'quiet']
SWING_MODE_KEYS = ['default', 'swing_full', 'fixed_upmost', 'fixed_middle_up', 'fixed_middle', 'fixed_middle_low', 'fixed_lowest', 'swing_downmost', 'swing_middle_low', 'swing_middle', 'swing_middle_up', 'swing_upmost']
SWING_HORIZONTAL_MODE_KEYS = ['default', 'full_swing', 'fixed_leftmost', 'fixed_middle_left', 'fixed_middle', 'fixed_middle_right', 'fixed_rightmost']

def _load_translations_from_json_sync(language):
    """Load translations from JSON files."""
    try:
        current_dir = os.path.dirname(__file__)
        json_file = os.path.join(current_dir, 'translations', f'{language}.json')

        if os.path.exists(json_file):
            with open(json_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        _LOGGER.error(f"Could not load translations from {json_file}: {e}")
    return {}

async def load_translations_from_json(hass, language):
    """Load translations from JSON files."""
    return await hass.async_add_executor_job(_load_translations_from_json_sync, language)

async def get_translations_data(hass, language=None):
    """Get translations data with guaranteed English fallback."""
    lang = language or hass.config.language or 'en'

    if lang != 'en':
        translations = await load_translations_from_json(hass, lang)
        if translations:
            return translations, lang
        _LOGGER.info(f"Language {lang} not found, using English")

    translations = await load_translations_from_json(hass, 'en')
    return translations, 'en'

async def get_all_translated_modes(hass, language=None):
    """Get all translated modes from JSON files."""
    translations, used_lang = await get_translations_data(hass, language)

    state_attributes = translations.get('entity', {}).get('climate', {}).get('gree', {}).get('state_attributes', {})

    mode_configs = {
        'fan_mode': FAN_MODE_KEYS,
        'swing_mode': SWING_MODE_KEYS,
        'swing_horizontal_mode': SWING_HORIZONTAL_MODE_KEYS
    }

    result = {}
    for mode_type, keys in mode_configs.items():
        if mode_type in state_attributes and 'state' in state_attributes[mode_type]:
            mode_translations = state_attributes[mode_type]['state']
            translated_modes = []
            for key in keys:
                translated_value = mode_translations.get(key, key)
                translated_modes.append(translated_value)
            result[mode_type] = translated_modes
        else:
            _LOGGER.warning(f"Missing {mode_type} section in {used_lang}.json - using keys as fallback")
            result[mode_type] = keys

    return result

async def get_translated_name(hass, language=None):
    """Get translated component name."""
    translations, used_lang = await get_translations_data(hass, language)
    title = translations.get('config', {}).get('title')
    return title or 'Gree Climate'

def get_mode_key_by_index(mode_type, index):
    """Get mode key by index."""
    mode_keys = {
        'fan_mode': FAN_MODE_KEYS,
        'swing_mode': SWING_MODE_KEYS,
        'swing_horizontal_mode': SWING_HORIZONTAL_MODE_KEYS
    }
    keys = mode_keys.get(mode_type, [])
    return keys[index] if 0 <= index < len(keys) else None

def get_mode_index_by_key(mode_type, key):
    """Get mode index by key."""
    mode_keys = {
        'fan_mode': FAN_MODE_KEYS,
        'swing_mode': SWING_MODE_KEYS,
        'swing_horizontal_mode': SWING_HORIZONTAL_MODE_KEYS
    }
    keys = mode_keys.get(mode_type, [])
    try:
        return keys.index(key)
    except ValueError:
        return None
