# Tuiss2HA

This adds support for Blinds2go Electronic blinds, powered by the Tuiss Smartview platform (if other brands exist they should work, but are untested). These blinds use bluetoth low energy and are controlled through a simple cover interface.


## Before Integration to Home Assistant ##
To get started you need to download and use the Tuiss Smartview app to set the upper and bottom limits of the blinds.

## Installation ##
1. Add the integration from the HACs marketplace ([instructions here](https://hacs.xyz/docs/configuration/basic))
2. Restart Home Assistant if required
3. Click Settings
4. Click Integration
5. Click the + icon
6. Select Tuiss SmartView from the dropdown
7. Enter the MAC address from the tag including in your blind, or written within the top bracket of the blind, close to where the battery is plugged in
8. Give the blind a name

## Features ##

### Currently Supported ###
- Set position
- Open 
- Close

### Planned Featuresure ###
- *Battery status* - this is not yet included, but being looked into


## Limitations ##
- *Open and Close status* - currently the opening and closing status of the blind is not included, it will only report on if the blind is Open and Closed, not while it is moving


## Troubleshooting ##
- I've only testing with HAOS installed on a raspberry pi4b and the  Bluetooth module built in did not work, so I had to use a couple ESP32 devices with Bluetooth proxy software installed (See [here](https://esphome.io/components/bluetooth_proxy.html))
- Sometimes the devices take a few attempts to connect, so expect some delay to commmands (though much improved from HA 2023-07 onwards if using ESPhome)
