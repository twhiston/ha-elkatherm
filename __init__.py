"""Initialization of the Elkatherm integration."""
from __future__ import annotations

import logging
from typing import Any

import paho.mqtt.client as mqtt
import requests
import json
import time
import threading

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    LOGIN_URL,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_PATH,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Elkatherm from a config entry."""
    coordinator = ElkathermCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    if not await coordinator.async_start():
        raise ConfigEntryNotReady("Failed to connect to Elkatherm")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN].pop(entry.entry_id)
    coordinator.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok


class ElkathermCoordinator:
    """Manages the MQTT connection and token lifecycle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._email = entry.data[CONF_EMAIL]
        self._password = entry.data[CONF_PASSWORD]
        self._token: str | None = None
        self._devices: list[dict] = []
        self._mqtt_client: mqtt.Client | None = None
        self._running = False
        self._device_states: dict[str, dict] = {}
        self._listeners: list[callable] = []

    def _do_login(self) -> dict:
        """Log in and return the response."""
        body = f"Username={self._email}&Password={self._password}"
        resp = requests.post(
            LOGIN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    async def async_login(self) -> bool:
        """Refresh the JWT token and device list."""
        try:
            result = await self.hass.async_add_executor_job(self._do_login)
            self._token = result["token"]
            self._devices = result.get("devicesList", [])
            _LOGGER.info("Logged in successfully, %d devices found", len(self._devices))
            return True
        except Exception as err:
            _LOGGER.error("Login failed: %s", err)
            return False

    def get_device_id(self, mac: str) -> str | None:
        """Get the device UUID for a given MAC."""
        for d in self._devices:
            if d["mac"] == mac:
                return d["deviceID"]
        return None

    def get_mac(self, device_id: str) -> str | None:
        """Get the MAC for a given device UUID."""
        for d in self._devices:
            if d["deviceID"] == device_id:
                return d["mac"]
        return None

    @property
    def devices(self) -> list[dict]:
        return self._devices

    @property
    def token(self) -> str | None:
        return self._token

    def register_listener(self, callback: callable) -> None:
        """Register a callback for device state updates."""
        self._listeners.append(callback)

    def unregister_listener(self, callback: callable) -> None:
        """Remove a registered listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self, mac: str, state: dict) -> None:
        """Notify all listeners of a state update (called from MQTT thread)."""
        for cb in self._listeners:
            try:
                self.hass.loop.call_soon_threadsafe(cb, mac, state)
            except Exception:
                _LOGGER.exception("Listener error")

    def get_device_state(self, mac: str) -> dict | None:
        """Get the latest known state for a device."""
        return self._device_states.get(mac)

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """Called when MQTT connects."""
        _LOGGER.info("MQTT connected with rc=%s", rc)
        if rc == 0:
            for device in self._devices:
                mac = device["mac"]
                uid = device["deviceID"]
                client.subscribe(f"{mac}/{uid}")
                client.subscribe(f"{mac}/{uid}/program")
                client.subscribe(f"+/+/{mac}/{uid}")
                client.subscribe(f"+/+/{mac}/{uid}/program")
                client.subscribe(f"+/+/{mac}/{uid}/actuators")
                
                # Request current status by publishing {} to UUID/MAC
                client.publish(f"{uid}/{mac}", "{}")
            
            # Schedule retries for the status request
            def _retry_status():
                for device in self._devices:
                    client.publish(f"{device['deviceID']}/{device['mac']}", "{}")
            
            # Retry after 5, 15, and 30 seconds
            timer = threading.Timer(5.0, _retry_status)
            timer.daemon = True
            timer.start()
            
            timer2 = threading.Timer(15.0, _retry_status)
            timer2.daemon = True
            timer2.start()
            
            timer3 = threading.Timer(30.0, _retry_status)
            timer3.daemon = True
            timer3.start()


    def _on_mqtt_message(self, client, userdata, msg):
        """Called when an MQTT message arrives."""
        try:
            _LOGGER.debug("MQTT message on %s: %s", msg.topic, msg.payload[:200])
            payload = json.loads(msg.payload)
            parts = msg.topic.split("/")
            # Handle both MAC/UUID (2 parts) and +/+/MAC/UUID (4 parts)
            mac = parts[0] if len(parts) == 2 else parts[2]
            self._device_states[mac] = payload
            self._notify_listeners(mac, payload)
        except Exception as err:
            _LOGGER.warning("Failed to process MQTT message on %s: %s", msg.topic, err)



    def _mqtt_loop(self):
        """Run the MQTT client loop (in a thread)."""
        while self._running:
            try:
                if self._mqtt_client:
                    self._mqtt_client.loop(timeout=1.0)
            except Exception:
                _LOGGER.exception("MQTT loop error")
                time.sleep(5)

    async def async_start(self) -> bool:
        """Start the coordinator: login and connect MQTT."""
        if not await self.async_login():
            return False

        return await self.async_connect_mqtt()

    async def async_connect_mqtt(self) -> bool:
        """Connect to the MQTT broker."""
        if self._token is None:
            return False

        try:
            client = mqtt.Client(
                client_id=f"elkatherm/ha/{self._email}",
                transport="websockets",
                protocol=mqtt.MQTTv311,
            )
            client.ws_set_options(path=MQTT_PATH)
            client.username_pw_set(self._email, self._token)
            client.on_connect = self._on_mqtt_connect
            client.on_message = self._on_mqtt_message

            def _setup_tls():
                client.tls_set()

            await self.hass.async_add_executor_job(_setup_tls)

            def _connect():
                client.connect(MQTT_HOST, MQTT_PORT, 30)

            await self.hass.async_add_executor_job(_connect)

            self._mqtt_client = client
            self._running = True

            thread = threading.Thread(target=self._mqtt_loop, daemon=True)
            thread.start()

            _LOGGER.info("MQTT connected to %s", MQTT_HOST)
            return True

        except Exception as err:
            _LOGGER.error("MQTT connection failed: %s", err)
            return False


    def publish_command(self, mac: str, payload: dict) -> None:
        """Publish a command to a device."""
        device_id = self.get_device_id(mac)
        if device_id is None or self._mqtt_client is None:
            _LOGGER.warning("Cannot publish: device %s not found", mac)
            return

        topic = f"{device_id}/{mac}"  # REVERSED!
        self._mqtt_client.publish(topic, json.dumps(payload))
        _LOGGER.debug("Published to %s: %s", topic, payload)


    def stop(self):
        """Stop the coordinator."""
        self._running = False
        if self._mqtt_client:
            try:
                self._mqtt_client.disconnect()
            except Exception:
                pass
            self._mqtt_client = None
