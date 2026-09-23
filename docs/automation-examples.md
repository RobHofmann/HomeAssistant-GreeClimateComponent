# Automation examples

Ideas for automations with the entities of this integration. The examples use a device named **Living Room AC** in an English Home Assistant, with the entity IDs Home Assistant gives by default. Your IDs can differ: Home Assistant builds them from the device name and your language, and you may have renamed them. Copy them from the device page. See [entities.md](entities.md) for the full list.

All examples use the automation syntax of Home Assistant 2024.10 and later, which every supported version has.

## Cool the room when it gets warm

The unit's own room sensor triggers the automation. The action sets the mode and the temperature in one call.

```yaml
automation:
  - alias: "Living room: cool when warm"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.living_room_ac_indoor_temperature
        above: 26
        for: "00:10:00"
    conditions:
      - condition: time
        after: "09:00:00"
        before: "22:00:00"
    actions:
      - action: climate.set_temperature
        target:
          entity_id: climate.living_room_ac
        data:
          hvac_mode: cool
          temperature: 23
```

## Turn off when a window is open

```yaml
automation:
  - alias: "Living room: AC off when window open"
    triggers:
      - trigger: state
        entity_id: binary_sensor.living_room_window
        to: "on"
        for: "00:05:00"
    conditions:
      - condition: not
        conditions:
          - condition: state
            entity_id: climate.living_room_ac
            state: "off"
    actions:
      - action: climate.turn_off
        target:
          entity_id: climate.living_room_ac
```

## Sleep mode and quiet fan at night

Sleep is only available in Cool and Heat. The condition keeps the automation from failing in other modes. Quiet is a fan mode, not a switch.

```yaml
automation:
  - alias: "Living room: night mode"
    triggers:
      - trigger: time
        at: "23:00:00"
    conditions:
      - condition: state
        entity_id: climate.living_room_ac
        state:
          - cool
          - heat
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.living_room_ac_sleep
      - action: climate.set_fan_mode
        target:
          entity_id: climate.living_room_ac
        data:
          fan_mode: quiet
```

The unit ignores Quiet while Power Save or Smart Heat 8°C is on. Turn those off first if you use them.

## Display light off at night

The simplest way is the **Auto Display Light** switch, which turns the display on and off with the unit. For a fixed schedule:

```yaml
automation:
  - alias: "Living room: AC display off at night"
    triggers:
      - trigger: time
        at: "22:30:00"
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.living_room_ac_display_light

  - alias: "Living room: AC display on in the morning"
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.living_room_ac_display_light
```

## Notify on a fault

The **Fault Detection** binary sensor exists when the unit reports the fault property.

```yaml
automation:
  - alias: "Living room: AC fault"
    triggers:
      - trigger: state
        entity_id: binary_sensor.living_room_ac_fault_detection
        to: "on"
    actions:
      - action: notify.notify
        data:
          title: "Air conditioner"
          message: "The living room AC reports a fault."
```

## Frost protection when nobody is home

Smart Heat 8°C keeps the room at 8°C. It only exists in Heat mode, so the automation sets the mode first.

```yaml
automation:
  - alias: "Living room: frost protection"
    triggers:
      - trigger: state
        entity_id: zone.home
        to: "0"
        for: "01:00:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.living_room_ac_outdoor_temperature
        below: 5
    actions:
      - action: climate.set_hvac_mode
        target:
          entity_id: climate.living_room_ac
        data:
          hvac_mode: heat
      - action: switch.turn_on
        target:
          entity_id: switch.living_room_ac_smart_heat_8oc
```

The `8oc` in the entity ID is how Home Assistant writes the name **Smart Heat 8ºC**. Check the exact ID on the device page.

## Read raw properties in a script

The `get_prop_values` action returns a response, so a script can use it. This one sends the power and mode values to a notification. See [actions.md](actions.md) for the response shape.

```yaml
script:
  living_room_ac_raw_state:
    alias: "Living room AC: raw state"
    sequence:
      - action: gree_custom.get_prop_values
        data:
          device_id: 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d
          prop_list:
            - Pow
            - Mod
            - SetTem
        response_variable: result
      - action: notify.notify
        data:
          message: "Living room AC: {{ result.states }}"
```

Find the `device_id` in the URL of the device page.

## Things to know

- A change you make is sent right away and followed by a refresh, so the entities update within a second or two.
- Mode dependent switches are unavailable outside their modes. An action on an unavailable switch fails. Set the mode first, or add a condition, as the examples do.
- With **Restore Entities** on, the integration sends the last Home Assistant state to the unit after a restart. An automation that runs at startup can race with that. Give it a short delay.
