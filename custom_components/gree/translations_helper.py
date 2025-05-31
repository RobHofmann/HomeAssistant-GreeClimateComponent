"""Translation helper for Gree Climate component."""
import logging
import json
import os
import aiofiles

_LOGGER = logging.getLogger(__name__)

# Translation keys for modes
FAN_MODE_KEYS = ['auto', 'low', 'medium-low', 'medium', 'medium-high', 'high', 'turbo', 'quiet']
SWING_MODE_KEYS = ['default', 'swing_full', 'fixed_upmost', 'fixed_middle_up', 'fixed_middle', 'fixed_middle_low', 'fixed_lowest', 'swing_downmost', 'swing_middle_low', 'swing_middle', 'swing_middle_up', 'swing_upmost']
PRESET_MODE_KEYS = ['default', 'full_swing', 'fixed_leftmost', 'fixed_middle_left', 'fixed_middle', 'fixed_middle_right', 'fixed_rightmost']

# Default English fallback modes
FAN_MODES_EN = ['Auto', 'Low', 'Medium-Low', 'Medium', 'Medium-High', 'High', 'Turbo', 'Quiet']
SWING_MODES_EN = ['Default', 'Swing in full range', 'Fixed in the upmost position', 'Fixed in the middle-up position', 'Fixed in the middle position', 'Fixed in the middle-low position', 'Fixed in the lowest position', 'Swing in the downmost region', 'Swing in the middle-low region', 'Swing in the middle region', 'Swing in the middle-up region', 'Swing in the upmost region']
PRESET_MODES_EN = ['Default', 'Full swing', 'Fixed in the leftmost position', 'Fixed in the middle-left position', 'Fixed in the middle position','Fixed in the middle-right position', 'Fixed in the rightmost position']

# Only translate the component name for users
DEFAULT_NAMES = {
    'ru': 'Gree Климат',
    'en': 'Gree Climate'
}

async def load_translations_from_json(language):
    """Load translations from JSON files (for UI modes) - async version."""
    try:
        # Get the directory where this file is located
        current_dir = os.path.dirname(__file__)
        json_file = os.path.join(current_dir, 'translations', f'{language}.json')

        if os.path.exists(json_file):
            async with aiofiles.open(json_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
                return data.get('entity', {}).get('climate', {}).get('gree', {}).get('state_attributes', {})
    except Exception as e:
        _LOGGER.debug(f"Could not load translations from {json_file}: {e}")

    return {}

async def get_translated_modes(hass, mode_type, keys, fallback, language=None):
    """Get translated mode names based on Home Assistant language - async version."""
    try:
        # Use provided language or get the current language from Home Assistant
        if language:
            detected_language = language
            _LOGGER.info(f"Using manually specified language: {detected_language}")
        else:
            detected_language = hass.config.language or 'en'
            _LOGGER.info(f"Home Assistant language detected: {detected_language}")
            _LOGGER.info(f"hass.config object: {hass.config}")
            _LOGGER.info(f"Available hass.config attributes: {dir(hass.config)}")

        # Load translations from JSON files
        translations = await load_translations_from_json(detected_language)

        if mode_type in translations and 'state' in translations[mode_type]:
            mode_translations = translations[mode_type]['state']
            translated_modes = []
            for key in keys:
                translated_modes.append(mode_translations.get(key, fallback[keys.index(key)]))
            _LOGGER.info(f"Using {detected_language} translations for {mode_type}: {translated_modes}")
            return translated_modes
        else:
            _LOGGER.info(f"No translations found for {mode_type} in language {detected_language}")

    except Exception as e:
        _LOGGER.error(f"Error getting translations for {mode_type}: {e}")

    # Fallback to English
    _LOGGER.info(f"Using English fallback for {mode_type}")
    return fallback

def get_mode_key_by_index(mode_type, index):
    """Get mode key by index for a specific mode type."""
    if mode_type == 'fan_mode':
        return FAN_MODE_KEYS[index] if 0 <= index < len(FAN_MODE_KEYS) else None
    elif mode_type == 'swing_mode':
        return SWING_MODE_KEYS[index] if 0 <= index < len(SWING_MODE_KEYS) else None
    elif mode_type == 'preset_mode':
        return PRESET_MODE_KEYS[index] if 0 <= index < len(PRESET_MODE_KEYS) else None
    return None

def get_mode_index_by_key(mode_type, key):
    """Get mode index by key for a specific mode type."""
    try:
        if mode_type == 'fan_mode':
            return FAN_MODE_KEYS.index(key)
        elif mode_type == 'swing_mode':
            return SWING_MODE_KEYS.index(key)
        elif mode_type == 'preset_mode':
            return PRESET_MODE_KEYS.index(key)
    except ValueError:
        pass
    return None

def get_translated_name(hass, language='en'):
    """Get translated component name based on Home Assistant language."""
    try:
        if language:
            detected_language = language
            _LOGGER.info(f"Using manually specified language for component name: {detected_language}")
        else:
            detected_language = hass.config.language
            _LOGGER.info(f"Component name language detected: {detected_language}")
        return DEFAULT_NAMES.get(detected_language, DEFAULT_NAMES['en'])
    except Exception as e:
        _LOGGER.error(f"Error getting translated name: {e}")
        return DEFAULT_NAMES['en']
