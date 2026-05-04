"""Constants for the Elkatherm integration."""

DOMAIN = "elkatherm"
MANUFACTURER = "Elkatherm / eComfort"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

LOGIN_URL = "https://elkatherm.udms.smarthomescomfort.com/api/users/login"
MQTT_HOST = "mqtt.api.innentech.ch"
MQTT_PORT = 443
MQTT_PATH = "/mqtt"

# HVAC modes we support
HVAC_MANUAL = "M"  # Manual mode
HVAC_PROGRAM = "P"  # Program mode
HVAC_OFF = "O"  # Off / antifrost only (no explicit off, but we can set low temp)
