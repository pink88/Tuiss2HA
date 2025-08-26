# Tuiss2HA
This adds support for Tuiss Smartview BLE blinds. These blinds use Bluetooth Low Energy and are controlled through a simple cover interface. This integration does not support RF control.


## Supported Tuiss Hardware Versions and Prerequisites ##
The following hardware versions have been tested and confirmed as working, but other versions should be supported.

- TS3000: has an external battery pack that must be connected to the blind before use via a cable. It is charged with a DC barrel plug.
- TS5200: has a battery pack integrated with the blind housing and is charged via USB-C input on the bottom of the blind. Additionally, it has a button to the rear on the charge port allowing manual control of the blind. Supports variable movement speeds.
- TS2600/TS2900/TS5001/TS5101: Roller blinds which support variable movement speeds.


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

### Battery State ###
An accurate battery percentage is not provided by the blind, but it is possible to return two states:
1. **Normal** - battery is good
2. **Low** - battery needs charging

To accomplish this, an action has been provided: 'tuiss2ha.get_battery_status'. This can be called manually from Developer tools -> Actions or included as part of an automation which It's recommended to run this on a weekly schedule. The resulting battery state of "Normal" or "Low" is then recorded against the Battery entity. The automation can then send a notification if the battery state is returned as low from the action. For example:

        alias: Blinds_Battery_Notify
        description: ""
        trigger:
         - platform: time
           at: "02:00:00"
        condition: []
        action:
          - service: tuiss2ha.get_battery_status
            target:
              entity_id:
                - binary_sensor.hallway_blind_battery
                - binary_sensor.study_blind_battery
            data: {}
          - if:
              - condition: state
                entity_id: binary_sensor.hallway_blind_battery
                state: "on"
            then:
              - service: notify.iPhone
                data:
                  message: Hallway Blind battery is low
          - if:
              - condition: state
                entity_id: binary_sensor.study_blind_battery
                state: "on"
            then:
              - service: notify.iPhone
                data:
                   message: Study battery is low


### Poll for Blind Position ###
The blind will not update its position within Home Assistant if controlled using the Tuiss app or Bluetooth remotes. To compensate, an action 'tuiss2ha.get_blind_position' has been provided. This can be called manually from Developers -> Actions or included as part of an automation. The automation can be set to run periodically throughout the day to update the position. I do not recommend running this more than hourly as it will likely drain your blinds' batteries.

### Control with Decimal Precision ###
To overwrite Home Assistant's built in integer accuracy, you can use the 'tuiss2ha.set_blind_position' action, which allows for up to 1 decimal place of precision. This can be called manually from Developer tools -> Actions or from within automations.

### Set Blind Speed ###
For supported models, you can set the speed of the blind motor using the 'tuiss2ha.set_blind_speed' action. This can be called manually from Developer tools -> Actions or from within automations. The available speeds are "Standard", "Comfort", and "Slow".

### Simultaneous Blind Positioning ###
To move multiple blinds to the same position at exactly the same time, you can use the 'tuiss2ha.simultaneous_blind_positioning' action. This is useful for creating synchronized scenes, like closing all blinds in a room at once. This action is designed specifically for simultaneous movement; for standard, sequential automations, it is better to use Home Assistant's built-in `cover.set_cover_position` action or this integrations 'tuiss2ha.set_blind_position' acton.

## Configuration Options ##
Configuration options can be set from the Tuiss2HA Integration screen in Home Assistant once you have added a blind.
- **Invert `set_blind_position`**: If you notice that the provided `set_blind_position` action is giving you the opposite result to what you expect (e.g. instead of 75% open, it shows as 75% closed), then you can toggle this option.
- **Reconnection attempts**: Sometimes devices take a few attempts to connect, so expect some delay to commands. This may also be a result of too many Bluetooth devices in your network, not enough adapters, or the distance between the blind and the adapter being too large. You can change the maximum number of retry attempts using this option. For connection issues, try moving devices closer or increasing the number of Bluetooth adapters/proxies.
- **Check for blind position on restart**: If you use the Tuiss app or a remote control to move the blinds in addition to this integration, you may want Home Assistant to fetch the latest position of a blind when it is restarted using this option.
- **Blind motor speed**: For supported models, the speed of the blind can be set. There are three speeds to select from: Standard (fastest), Comfort, and Slow (slowest). By default, the speed will be set to Standard.
- **Favourite position**: Allows you to specify a percentage value for your favourite position. This can then be activated using the button entity provided by the integration.


## Troubleshooting ##
- If the blind is slow to respond, failing to connect, it will usually be due to signal strength. -60dBm or higher is Excellent -61 to -75 dBm is Good, -76 dbM to -90 dBm is Weak and below -90 dBm is Very Weak. Improving this with more or closer Bluetooth adapter/proxies.
- If you are getting errors when adding a blind, some users report that removing Shelly Bluetooth proxies resolves the issue. This appears to be a limitation of how Home Assistant decides which proxy to use and sometimes selects the Shelly proxy which cannot retain the active connection required by this integration.


## Limitations ##
1. *Setting the top and bottom thresholds of the blind* - you still need to pair with and use the Tuiss Smartview app to set these values for older blind models.
2. *Real-time blind positioning* - only works after the first use as this initial run is required to calibrate the speed of your blind motor.
I have tested this integration with HAOS installed on a Raspberry Pi 4B and the built-in Bluetooth module did not work. I had to use a few ESP32 devices with Bluetooth proxy software installed using the excellent ESPHome (See [this link](https://esphome.io/components/bluetooth_proxy.html))
