# HA Elkatherm / eComfort Radiator Integration

Home Assistant custom integration for Elkatherm and eComfort WiFi-connected electric radiators.

## Features
- Climate entities for each radiator
- Temperature control (manual mode)
- Schedule/program mode switching
- Real-time status updates via MQTT

## Installation via HACS
1. Go to HACS → Integrations → Three dots → Custom repositories
2. Add `https://github.com/twhiston/ha-elkatherm` as type "Integration"
3. Click "Download" on the Elkatherm integration
4. Restart Home Assistant
5. Go to Settings → Devices & Services → Add integration → Search "Elkatherm"
6. Enter your ecomfort app email and password

## Manual Installation
Copy `custom_components/elkatherm/` to your HA config directory and restart.
