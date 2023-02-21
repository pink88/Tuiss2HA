# HA2Tuiss

This adds support for Blinds2go Electronic blinds, powered by the Tuiss Smartview platform. These blinds use bluetoth low energy and are controlled through a simple cover interface.


Before Integration to Home Assistant
To get started you need to download and use the Tuiss Smartview app to set the upper and bottom limits of the blinds.

Installation
Add the integration from the HACs marketplace (see here for instructions on how)
Restart Home Assistant if required
Click Settings
Click Integration
Click te + icon
Select Tuiss SmartView from the dropdown
Enter the MAC address from the tag including in your blind, or written within the top bracket of the blind, close to where the battery is plugged in
Give the blind a name

Features
Set position
Open 
Close

Limitations
Battery status - this is not yet included, but being looked into
Open and Close status - currently the opening and closing status of the blind is not included, it will only report on if the blind is Open and Closed, not while it is moving


Troubleshooting
The Bluetooth module built into a Raspberry Pi 4B does not work, I use a couple ESP32 devices with Bluetooth proxy software installed (See here)
SOmetimes the devices take a few attempts to connect, so expect some delay to commmands
Sometimes a device will fair to opperate, this is a known bug and I am trying to debug, though It appears to be caused by the EPS32 software or the HomeAssistant bluetooth integration

