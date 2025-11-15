# Tuiss2HA

This integration adds support for Tuiss SmartView blinds. These blinds use Bluetooth Low Energy and are exposed in Home Assistant as standard cover entities. Note: this integration does not support RF control (used by the Tuiss remote); for RF control you can use a device such as the [Sonoff RF Bridge](https://esphome.io/components/rf_bridge/).

For best results, I strongly recommend using [ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy.html) rather than the built-in Bluetooth adapter on Home Assistant hardware or a Raspberry Pi.

## Supported Tuiss hardware and prerequisites

The following hardware versions have been tested and confirmed to work. Other versions may also be compatible.

- **TS3000**: External battery pack connected by cable; charged via a DC barrel plug.
- **TS5200 / TS5300**: Battery pack integrated into the blind housing; charged via USB‑C. Includes a manual control button near the charge port. Supports variable movement speeds.
- **TS2600 / TS2900 / TS5001 / TS5101**: Roller blinds that support variable movement speeds.

## Installation and adding your devices ##
*Note: Devices should be automatically discovered if they are in range of a Bluetooth adapter/proxy once you have completed steps 1-3. If not you can add manually, though doing so may mean that your blinds are out of Bluetooth range.*

1. Complete the setup of your blind in the Tuiss Smartview app.
2. Add the integration from the HACS marketplace ([instructions here](https://hacs.xyz/docs/configuration/basic)).
3. Restart Home Assistant if required.
4. Go to **Settings > Devices & Services**.
5. Click the **+ Add Integration** button.
6. Select **Tuiss SmartView** from the dropdown.
7. Enter the MAC address from the tag included with your blind, or written within the top bracket of the blind, close to where the battery is plugged in.
8. Give the blind a name.
9. Click **Submit**.


## Features ##
- Set position
- Open 
- Close
- Stop
- Battery State (through action)
- Signal Strength
- Favourite position
- Decimal Blind position (through action)
- Simultaneous blind positioning (through action)
- Force Unlock blind (through action)

*Note: All actions can be run manually from (Developer Tools → Actions) or included in an automation.

### Battery State ###
Tuiss blinds do not provide an accurate battery percentage. Instead, the integration exposes a binary battery state:
1. **Normal** - battery is good
2. **Low** - battery needs charging

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

Use `tuiss2ha.simultaneous_blind_positioning` to move multiple blinds to the same position at the same time. This is useful for synchronized scenes. Note: this requires sufficient Bluetooth proxies/adapters to handle multiple concurrent connections.

## Configuration options

From the integration's Options screen you can configure:

- **Reconnection attempts**: number of retries before giving up on a connection.
- **Check position on restart**: fetch current position after Home Assistant restarts.
- **Blind motor speed**: for supported models (Standard, Comfort, Slow).
- **Favorite position**: a percentage value that can be triggered with the "Go to Favorite Position" action.

## Troubleshooting

- Weak or unreliable connections are usually caused by poor signal strength. Measured RSSI: -60 dBm or higher = Excellent; -61 to -75 dBm = Good; -76 to -90 dBm = Weak; below -90 dBm = Very weak. Improve coverage with more or closer Bluetooth adapters/proxies.
- If adding a blind fails, some users have reported issues with Shelly Bluetooth proxies. If you have a Shelly proxy, try removing it to see if discovery improves.
- If a blind is stuck in a locked state and not actively moving, you can either restart Home Assistant or call the `tuiss2ha.force_unlock` service (Developer Tools → Actions) or use an automation.

## Limitations

1. Setting top/bottom thresholds: older models may still require pairing with the Tuiss SmartView app to configure these values.
2. Real-time position updates: the first interaction is used to calibrate the motor speed; real-time positioning works reliably after that initial calibration.

## Contributing

Contributions, bug reports, and feature requests are welcome. Please open an issue or a pull request on GitHub.
