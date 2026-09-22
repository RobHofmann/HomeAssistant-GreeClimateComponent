# Entities

Every device gets one climate entity and a set of sensors, switches, selects and numbers. Which ones you get depends on three things:

1. **What the unit answers.** At setup, the integration asks the device for every property it knows. A property the device does not return is dropped. An entity is only created when the device answers the properties behind it. A unit with few features gets few entities.
2. **What you enabled.** The **Device Features and Modes** option decides which optional switches and selects are created. See [configuration.md](configuration.md#device-features).
3. **The current mode.** Some features only exist in some HVAC modes. The entity then shows as unavailable in the other modes.

Entity IDs start with the device name, followed by the entity name in the language of your Home Assistant. In English, a device named `Living Room AC` gets `climate.living_room_ac`, `sensor.living_room_ac_indoor_temperature`, `switch.living_room_ac_x_fan`, and so on. A Dutch Home Assistant gives `switch.living_room_ac_pieptoon` for the beeper. Copy the IDs from the device page. The examples below use `climate.your_ac`.

## Climate

The main entity. Its name is the device name.

| Part | What it does |
|---|---|
| HVAC mode | Auto, Cool, Dry, Fan only, Heat, Off. You choose the list at setup. Off turns the unit off, every other mode turns it on. |
| Target temperature | 16 to 30 degrees C, or 61 to 86 degrees F. Available when Heat, Cool or Auto is in the mode list. The step is the **Temperature Step** option. In Auto mode the unit uses its own factory setting, so a temperature sent with Auto is ignored and logged as a warning. |
| Current temperature | The unit's room sensor, converted to the unit's temperature scale. Replaced by the **External Temperature Sensor** when one is set. |
| Current humidity | The unit's humidity sensor, when it has one. Replaced by the **External Humidity Sensor** when one is set. |
| Fan mode | Auto, Low, Medium-Low, Medium, Medium-High, High, plus Turbo and Quiet when the unit has them. See below. |
| Swing mode | Vertical positions and swing ranges. |
| Horizontal swing mode | Horizontal positions and swing ranges, when the unit has them. |

Extra attribute: `current_outside_temperature`, the outdoor sensor value in the unit's temperature scale, when the unit has an outdoor sensor. Read it with `{{ state_attr('climate.your_ac', 'current_outside_temperature') }}`.

### Turbo and Quiet

Turbo and Quiet are not fan speeds on the unit but separate features. The integration shows them as fan modes because that is how the remote presents them.

- **Turbo** runs the fan at its maximum. Only in Cool and Heat mode. Selecting it in another mode fails with a message.
- **Quiet** runs the fan at its most quiet speed.
- The unit ignores both while Power Save or Smart Heat 8°C is on. The integration logs that and leaves the setting for when those are turned off.
- Selecting a normal speed turns Turbo and Quiet off.

### Temperature scale

The unit has its own temperature scale, Celsius or Fahrenheit, which you change with the **Temperature Units** select. The climate entity follows the unit, and Home Assistant converts to your display units. Fahrenheit values come from the unit's own lookup table, not from a formula.

## Sensors

Created when the unit has the sensor. Nothing to enable.

| Entity | Unit | Meaning |
|---|---|---|
| Indoor Temperature | °C | The room temperature the unit measures. |
| Outdoor Temperature | °C | The outdoor unit's temperature sensor. |
| Indoor Humidity | % | The room humidity the unit measures. |

Some units report temperatures with an offset of 40. The integration detects that from the values it sees and corrects it.

## Binary sensor

| Entity | Meaning |
|---|---|
| Fault Detection | On when the unit reports a fault. Diagnostic category. Created when the unit reports the fault property. |

## Switches

Each switch needs its feature enabled in **Device Features and Modes**, and the unit must answer the property behind it.

| Switch | Feature | Available in | What it does |
|---|---|---|---|
| Fresh Air | Fresh Air | every mode | Opens the fresh air valve on units that have one. |
| X-Fan | X-Fan | Cool, Dry | Keeps the fan running for a while after the unit turns off, to dry the coil and prevent condensation. |
| Sleep | Sleep | Cool, Heat | Sleep mode: the unit changes the temperature slowly during the night. Turning it on turns Power Save and Smart Heat 8°C off. |
| Smart Heat 8ºC | 8ºC Smart Heat | Heat | Keeps the room at 8°C to prevent frost when nobody is home. Turning it on turns Sleep and Power Save off. The unit ignores the temperature and fan settings while it is on. |
| Health | Health | every mode | Health mode, also called cold plasma or ionizer. |
| Anti Direct Blow | Anti Direct Blow | every mode | Moves the deflector so the air does not blow straight at people. |
| Power Save | Energy Saving | Cool | Energy saving mode. Turning it on turns Sleep and Smart Heat 8°C off. The unit ignores the temperature and fan settings while it is on. |
| Display Light | Display Light | every mode | The display and indicator lights on the unit. Configuration category. |
| Display Auto Brightness | Display Auto Brightness | when Display Light is on | Lets the light sensor dim the display. Configuration category. |
| Beeper | Beeper | always | Whether the unit beeps when it receives a command. This is a flag the integration adds to every command, not a state that is read from the unit. Always available, even when the unit is offline. |

Two switches are integration features. They do not exist on the unit and their state is kept by Home Assistant. Both are in the configuration category.

| Switch | What it does |
|---|---|
| Auto X-Fan | Turns X-Fan on when you switch to Cool or Dry, and off in other modes. Needs the X-Fan feature. |
| Auto Display Light | Turns the display light on when the unit turns on, and off when it turns off. Needs the Display Light feature. |

## Selects

| Select | Feature | Available in | Options |
|---|---|---|---|
| Temperature Units | none, created when the unit answers the property | every mode | ºC, ºF. Changes the scale of the unit itself. Configuration category. |
| Humidity Control | Humidity Control | Cool, Dry | Disabled, Normal Dry, Smart Dry, Continuous Dry. Smart Dry only in Cool. Continuous Dry only in Dry. The other options fail with a message. |

## Numbers

| Number | Feature | Available in | Range |
|---|---|---|---|
| Humidity Control Target | Humidity Control | Cool or Dry, with Humidity Control on Normal Dry | 40 to 80 % in Cool, 30 to 70 % in Dry, steps of 5. |

## Availability

An entity is available when the last poll succeeded and the device reports itself as reachable. One failed poll makes the entities unavailable until the next good poll. A poll fails when every retry fails, so with the defaults that takes up to 3 attempts of 10 seconds.

With **Disable Available Check** on, the entities stay available whatever the device does. Use that when a device drops packets often and you prefer stale values over unavailable entities. Commands still fail when the device does not answer.

Mode dependent entities, such as X-Fan or Power Save, are unavailable outside their modes even when the device is reachable. The Beeper switch is always available.

## Restoring state after a restart

With **Restore Entities** on, which is the default, the integration sends the last known Home Assistant state to the device when it starts. That covers the climate entity (mode, fan, swing and target temperature) and the feature switches. Turn it off when Home Assistant should take over what the device is doing at that moment. That is useful when you also use the remote.

Three switches are always restored, whatever the option says: Beeper, Auto X-Fan and Auto Display Light. Their state lives in Home Assistant and not on the unit.

Sensors and selects are not restored. They show the device values as soon as the first poll comes in.

## Polling and pushed updates

The integration polls the device every **Scan Interval** seconds, 60 by default. A change you make in Home Assistant is sent right away and followed by a refresh, so the entities update within a second or two. A change made with the remote shows up at the next poll, or sooner when the device pushes its status, which cloud connected devices do.
