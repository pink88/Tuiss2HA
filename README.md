# Tuiss2HA
This adds support for Blinds2go Electronic blinds, powered by the Tuiss Smartview platform (if other brands exist they should work, but are untested). These blinds use bluetooth low energy and are controlled through a simple cover interface. As well as control of the blinds position through home assistant, this also includes 3 services.
1. get_battery_status: can be used to get the battery status (normal or low)
2. set_blind_position: allows setting decimal precision for the blind over home assistants built in integer position, which allows refined tilt controls in some models. 
3. get_blind_position: can be used to periodically poll your blinds to get their position, as using the Tuiss app or bluetooth remotes will not automatically update the position of the blind in home assistant due to limitations in the tuiss platform itself.

Note: This integration only controls blinds using BLE (bluetooth low energy), it will not control blinds that also or only support RF control.


## Before Integration to Home Assistant ##
To get started you need to download and use the Tuiss Smartview app to set the upper and bottom limits of the blinds.

Note: If you have a newer TS5200 device, you *must* add to the Tuiss Smartview app or the blind won't operate. See hardware versions below.

## Installation and adding your first device ##
1. Add the integration from the HACs marketplace ([instructions here](https://hacs.xyz/docs/configuration/basic))
2. Restart Home Assistant if required
3. Click Settings
4. Click Devices & Services
5. Click the "+ add integration" button
6. Select Tuiss SmartView from the dropdown
7. Enter the MAC address from the tag including in your blind, or written within the top bracket of the blind, close to where the battery is plugged in
8. Give the blind a name
9. Click Submit

### Tuiss Hardware Versions ###
Both known hardware versions from Tuiss / Blinds2Go are compatible with this integration. If unsure, you can identify from the name of the blind in the bluetooth discovery panel in HA.

#### TS3000 ####
The TS3000 has an external battery pack that must be connected to the blind before use via a cable. It is charged with a DC-style charger. No special setup is required.

#### TS5200 ####
The TS5200 has a battery pack integrated with the blind housing and charged with a USB-C input on the bottom of the blind. Additionally, it has a button to the rear on the charge port allowing manual control of the blind. First seen in blinds supplied from March 2025.

**Important:** For the TS5200 to work, it first must be 'activated' via the Tuiss SmartView app. The blind will chime and move slightly once activated. Following this, it can be added and used with this integration as normal. No further action is required within the app.

## Features ##
- Set position
- Open 
- Close
- Stop
- Battery State (through service)
- Decimal Blind position (through service)

### Battery State ###
An accurate battery percentage is not provided by the blind, but it is possible to return two states:
1. "Battery is good"
2. "Battery needs charging"

To accomplish this a service has been provided: "Tuiss2ha.Get_Battery_Status". This can be called manually from Developers -> Services or included as a part of an automation which I'd recommend runs on a weekly schedule. The resulting battery state of "Normal" or "Low" is then recorded against the Battery entity. The automation can then send a notification if the battery state is returned as low from the service. For example:

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
                   message: Study battery is low`


### Accurate Blind Position ###
The blind will not update its position within Home Assistant if controlled using the Tuiss app or bluetooth remotes. To compensate, a service "Tuiss2ha.Get_Blind_Position" has been provided. This can be called manually from Developers -> Actions or included as a part of an automation. The automation can be set to run periodically throughout the day to update the position. I would not recommend running this more than hourly as it will likely drain your blinds batteries (though I have not tested this).

### Decimal Precision ###
To overwrite home assistants built in integer accuracy, you can use the "Tuiss2ha.Set_Blind_Position" service, which allows for up to 1 decimal place of precision. This can be called manually from Developers -> Actions.

## Limitations ##
- Setting the top and bottom thresholds of the blind. Currently, you still need to pair with and use the Tuiss app to set these values.
- Realtime blind positioning will only work after the first use as this initial run is required to calibrate the speed of your blind motor.

## Troubleshooting ##
- I've only tested with HAOS installed on a Raspberry Pi4b and the built in Bluetooth module did not work, so I had to use a couple ESP32 devices with Bluetooth proxy software installed (See [here](https://esphome.io/components/bluetooth_proxy.html))
- Sometimes the devices take a few attempts to connect, so expect some delay to commmands (though much improved from HA 2023-07 onwards when using ESPhome)
- If you notice that the provided action "Get_Blind_Position" is giving you the opposite % to what you expect e.g. instead of 75% open, it shows as 75% closed, then a Switch entity has been provided to resolve this. By default the switch entity to set to True and this appears to work in most cases.
