"""Climate platform for Elkatherm radiators."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER, HVAC_MANUAL, HVAC_PROGRAM

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Elkatherm climate entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    import asyncio
    await asyncio.sleep(3)

    entities = []
    for device in coordinator.devices:
        entity = ElkathermClimate(coordinator, device, entry)
        entities.append(entity)

    async_add_entities(entities)


class ElkathermClimate(ClimateEntity):
    """Representation of an Elkatherm radiator."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF, HVACMode.AUTO]

    def __init__(self, coordinator, device: dict, entry: ConfigEntry) -> None:
        """Initialize the climate entity."""
        self._coordinator = coordinator
        self._device = device
        self._mac = device["mac"]
        self._device_id = device["deviceID"]
        self._attr_unique_id = f"elkatherm_{self._mac}"
        self._attr_name = device.get("name", f"Radiator {self._mac[-6:]}")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            name=self._attr_name,
            manufacturer=MANUFACTURER,
            model="Electric Radiator",
            sw_version=None,
        )

        self._state: dict | None = None
        self._attr_current_temperature: float | None = None
        self._attr_target_temperature: float | None = None
        self._attr_hvac_mode: HVACMode = HVACMode.HEAT
        self._attr_hvac_action: HVACAction = HVACAction.IDLE

        coordinator.register_listener(self._handle_state_update)

    @callback
    def _handle_state_update(self, mac: str, state: dict) -> None:
        """Handle an MQTT state update (called from event loop via call_soon_threadsafe)."""
        if mac != self._mac:
            return

        self._state = state
        self._attr_current_temperature = state.get("roomT")

        mode = state.get("mode", HVAC_MANUAL)
        if mode == HVAC_PROGRAM:
            self._attr_hvac_mode = HVACMode.AUTO
        else:
            self._attr_hvac_mode = HVACMode.HEAT

        if mode == HVAC_PROGRAM:
            self._attr_target_temperature = state.get("programT")
        else:
            self._attr_target_temperature = state.get("manualT")

        heating = state.get("heating", 0)
        self._attr_hvac_action = HVACAction.HEATING if heating else HVACAction.IDLE

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        temperature = round(temperature * 2) / 2

        payload = {
            "manualT": temperature,
            "manuelnaT": temperature,
        }

        await self.hass.async_add_executor_job(
            self._coordinator.publish_command, self._mac, payload
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            payload = {"manualT": 5, "manuelnaT": 5, "mode": HVAC_MANUAL}
        elif hvac_mode == HVACMode.AUTO:
            payload = {"mode": HVAC_PROGRAM}
        elif hvac_mode == HVACMode.HEAT:
            current = self._attr_target_temperature or 15
            payload = {"manualT": current, "manuelnaT": current, "mode": HVAC_MANUAL}
        else:
            return

        await self.hass.async_add_executor_job(
            self._coordinator.publish_command, self._mac, payload
        )

    async def async_turn_on(self) -> None:
        """Turn the radiator on."""
        current = self._attr_target_temperature or 18
        payload = {"manualT": current, "manuelnaT": current, "mode": HVAC_MANUAL}
        await self.hass.async_add_executor_job(
            self._coordinator.publish_command, self._mac, payload
        )

    async def async_turn_off(self) -> None:
        """Turn the radiator off."""
        payload = {"manualT": 5, "manuelnaT": 5, "mode": HVAC_MANUAL}
        await self.hass.async_add_executor_job(
            self._coordinator.publish_command, self._mac, payload
        )

    @property
    def available(self) -> bool:
        """Return if the device is available."""
        return self._state is not None
