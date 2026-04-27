# Tuiss2HA

This integration adds support for Tuiss SmartView blinds over Bluetooth Low Energy and provides an alternative to the Tuiss app. With this integration you will be able to  operate one or more blinds, check battery status, set movement limits, set local timers and control speeds. For best results, I strongly recommend using [ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy.html) rather than the built-in Bluetooth adapter on Home Assistant hardware or a Raspberry Pi, as the majority of connection issues will be due to poor coverage of your bluetooth network.

*This integration does not support RF control (used by the Tuiss remote); for RF control you can use a device such as the [Sonoff RF Bridge](https://esphome.io/components/rf_bridge/).*

## Supported Tuiss hardware and prerequisites

The following hardware versions have been tested and confirmed to work. Other versions may also be compatible.

- **TS3000**: External battery pack connected by cable; charged via a DC barrel plug.
- **TS5200 / TS5300**: Battery pack integrated into the blind housing; charged via USB‑C. Includes a manual control button near the charge port. Supports variable movement speeds.
- **TS2600 / TS2900 / TS5001 / TS5101**: Roller blinds that support variable movement speeds.

## Installation and adding your devices ##
*Note: Devices should be automatically discovered if they are in range of a Bluetooth adapter/proxy once you have completed steps 1-3. If your blinds are not discovered, it might mean that your blinds are out of Bluetooth range. Please check that you are able to connect to them using the Tuiss Smartview app from the same location as your bluetooth adapters and adjust positions accordingly. If they are still not discovered, you can add them manually buy following the remaining steps below.*

1. Complete the setup of your blind in the Tuiss Smartview app.
2. Add the integration from the HACS marketplace ([instructions here](https://hacs.xyz/docs/configuration/basic)).
3. Restart Home Assistant if required.
4. Go to **Settings > Devices & Services**.
5. Click the **+ Add Integration** button.
6. Select **Tuiss SmartView** from the dropdown.
7. Enter the MAC address from the tag included with your blind, or written within the top bracket of the blind, close to where the battery is plugged in.
8. Give the blind a name.
9. Click **Submit**.

Add to HACS: [![](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pink88&repository=Tuiss2HA&category=Integration)
Add to Home Assistant: [![](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tuiss2ha)

### Entities provided ###
- Cover
- Battery sensor
- Signal Strength sensor
- Favourite position button
- Timers (see Actions section below)

### Cover features ###
- Set position
- Open
- Close
- Stop

## Configuration options

From the integration's Options screen you can configure:

- **Reconnection attempts**: number of retries before giving up on a connection.
- **Check position on restart**: fetch current position after Home Assistant restarts.
- **Blind motor speed**: for supported models (Standard, Comfort, Slow).
- **Favorite position**: a percentage value that can be triggered with the "Go to Favorite Position" action.
- **Limits**: set the upper and lower boundaries of the blind which control how far the blind will move from open to closed.
- **Battery check interval (days)**: number of days between automatic battery checks performed when the blind next moves. Set to `0` (default) to disable automatic checks. If set, the blind will perform a battery check on the next movement when the last automatic check is older than this value. *NOTE: This doesn't work alongside the Simultaneous blind positioning action. If you want to use that feature, then check for the battery using the get_battery_status action detailed below instead.*

## Actions 
All actions can be run manually from (Developer Tools → Actions) or included in an automation.

### Battery State ###
Tuiss blinds do not provide an accurate battery percentage. Instead, the integration exposes a binary battery state:
1. **Normal** - battery is good
2. **Low** - battery needs charging

Automatic battery checks can be triggered by setting the "Battery check interval (days)" option (see Configuration options). When enabled, a battery check will run on the next movement if the last automatic check is older than the configured number of days.

Example automation to check batteries and notify when low:

```yaml
alias: Blinds battery notify
trigger:
  - platform: time
    at: "02:00:00"
action:
  - service: tuiss2ha.get_battery_status
    target:
      entity_id:
        - binary_sensor.hallway_blind_battery
        - binary_sensor.study_blind_battery
  - if:
      - condition: state
        entity_id: binary_sensor.hallway_blind_battery
        state: "on"
    then:
      - service: notify.mobile_app_your_phone
        data:
          message: "Hallway blind battery is low"
  - if:
      - condition: state
        entity_id: binary_sensor.study_blind_battery
        state: "on"
    then:
      - service: notify.mobile_app_your_phone
        data:
          message: "Study blind battery is low"
```

### Polling for blind position

If blinds are moved using the Tuiss app or a Bluetooth remote, Home Assistant will not automatically know the new position. Use the `tuiss2ha.get_blind_position` action to request the current position (manually or via automation). Running this too frequently will drain the blind battery; hourly or less is recommended.

### Decimal position control

Use the action `tuiss2ha.set_blind_position` to set positions with one decimal place of precision (0.0–100.0).

### Blind speed

Supported models allow setting the motor speed via `tuiss2ha.set_blind_speed`. Available speed options are: Standard, Comfort, and Slow. Default is Standard.

### Simultaneous blind positioning

Use `tuiss2ha.simultaneous_blind_positioning` to move multiple blinds to the same position at the same time or move eacb blind to their defined favourite position (see *Configuration options*). This is useful for synchronized scenes, howver this requires sufficient Bluetooth proxies/adapters to handle multiple concurrent connections.


### Add and Delete Timers

Timers allow the blind to store a position, time of day and day or week locally in its memory. Up to 6 timers can be set using this integration. 
You can add a timer using the `tuiss2ha.add_blind_timer` action and remove one using the `tuiss2ha.delete_blind_timer` action.
And timers that run will not update the position in Home Assistant, so you will need to run the `tuiss2ha.get_blind_position` manually or via an automation to update Home Assistant with the correct positions. 
The blinds allow for up to 16 timers to be set, however the first 10 are for exclusive use by the Tuiss app. Any timers set in the app will not appear in Home Assistant and vice versa, due to technical limitations.



## Troubleshooting

- Weak or unreliable connections are usually caused by poor signal strength. Measured RSSI: -60 dBm or higher = Excellent; -61 to -75 dBm = Good; -76 to -90 dBm = Weak; below -90 dBm = Very weak. Improve coverage with more or closer Bluetooth adapters/proxies.
- For supported models, check that your blinds firmware is up-to-date from within the Tuiss app
- If adding a blind fails, some users have reported issues with Shelly Bluetooth proxies. If you have a Shelly proxy, try removing it to see if discovery improves.
- If a blind is stuck in a locked state and not actively moving, you can either restart Home Assistant or call the `tuiss2ha.force_unlock` action (Developer Tools → Actions) or from an automation.


## Contributing

Contributions, bug reports, new model numbers and feature requests are welcome. Please open an issue or a pull request on GitHub.
