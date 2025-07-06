# Tuiss2HA
This adds support for Tuiss Smartview BLE blinds. These blinds use Bluetooth Low Energy and are controlled through a simple cover interface. This integration does not support RF control.

## Supported Tuiss Hardware Versions and Prerequisites ##
The following hardware versions have been tested and confirmed as working, but other versions should be supported.

- TS3000: has an external battery pack that must be connected to the blind before use via a cable. It is charged with a DC barrel plug.
- TS5200: has a battery pack integrated with the blind housing and is charged via USB-C input on the bottom of the blind. Additionally, it has a button to the rear on the charge port allowing manual control of the blind. Supports variable movement speeds.
-TS5001/TS5101: Roller blinds which support variable movement speeds.

Before conncting a blind to Home Assistant, first add the blind to the Tuiss Smartview app and follow the setup instruction to pair and to set the upper and lower limits.

## Installation and adding your first device ##
1. Complete the setup of your blind in the Tuiss Smartview app
2. Add the integration from the HACS marketplace ([instructions here](https://hacs.xyz/docs/configuration/basic))
3. Restart Home Assistant if required
4. Click Settings
5. Click Devices & Services
6. Click the "+ Add Integration" button
7. Select Tuiss SmartView from the dropdown
8. Enter the MAC address from the tag included with your blind, or written within the top bracket of the blind, close to where the battery is plugged in
9. Give the blind a name
10. Click Submit

*Note: Subsequent devices should be automatically discovered if they are in range of a Bluetooth adapter/proxy.*


## Features ##
- Set position
- Open 
- Close
- Stop
- Battery State (through action)
- Decimal Blind position (through action)

### Battery State ###
An accurate battery percentage is not provided by the blind, but it is possible to return two states:
1. "Normal" - battery is good
2. "Low" - battery needs charging

To accomplish this, an action has been provided: "Tuiss2ha.Get_Battery_Status". This can be called manually from Developer tools -> Actions or included as part of an automation which I'd recommend runs on a weekly schedule. The resulting battery state of "Normal" or "Low" is then recorded against the Battery entity. The automation can then send a notification if the battery state is returned as low from the action. For example:

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
The blind will not update its position within Home Assistant if controlled using the Tuiss app or Bluetooth remotes. To compensate, an action "Tuiss2ha.Get_Blind_Position" has been provided. This can be called manually from Developers -> Actions or included as part of an automation. The automation can be set to run periodically throughout the day to update the position. I do not recommend running this more than hourly as it will likely drain your blinds' batteries.

### Control with Decimal Precision ###
To overwrite Home Assistant's built in integer accuracy, you can use the "Tuiss2ha.Set_Blind_Position" action, which allows for up to 1 decimal place of precision. This can be called manually from Developer tools -> Actions or from within automations.

## Configuration Options and Troubleshooting ##
Configuration options can be set from the Tuiss2HA Integration screen in Home Assistant once you have added a blind.
- OPTION: If you notice that the provided action _"Set_Blind_Position"_ is giving you the opposite % to what you expect e.g. instead of 75% open, it shows as 75% closed, then you can toggle the configuration option _"Invert Set_Blind_Position"_. 
- OPTION: Sometimes the devices take a few attempts to connect, so expect some delay to commands. This may also be a result of too many Bluetooth devices in your network, not enough adapters or the distance between the blind and the adapter being too large. Try moving devces closer or increasing the number of Bluetooth adapters/proxies. You can change the maximum number of retry attempts using the configuration option _"Reconnection attempts"_.
- OPTION: If you use the Tuiss app or a remote control  to move the blinds in addition to this integration, you may want Home Assistant to fetch the latest position of a blind when it is restarted using configuration option _"Check for blind position on restart"_.
- OPTION: For supported models, the speed of the blind can be set. There are three speeds to select Standard (fastest) -> Comfort -> Slow (slowest). By default the speed will be set to Standard.

## Limitations ##
1. *Setting the top and bottom thresholds of the blind* - you still need to pair with and use the Tuiss Smartview app to set these values for older blind models.
2. *Real-time blind positioning* - only works after the first use as this initial run is required to calibrate the speed of your blind motor.
I have tested this integration with HAOS installed on a Raspberry Pi 4B and the built-in Bluetooth module did not work. I had to use a few ESP32 devices with Bluetooth proxy software installed using the excellent ESPHome (See [this link](https://esphome.io/components/bluetooth_proxy.html))
