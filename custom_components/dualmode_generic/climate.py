"""
Adds support for generic thermostat units that have both heating and cooling.

Originally based on the script at this thread:
https://community.home-assistant.io/t/heat-cool-generic-thermostat/76443/2

Modified to better confoarm to modern Home Assistant custom_component style.
"""
import asyncio
import logging
import asyncio

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE,
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_FAN,
    CURRENT_HVAC_DRY,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_FAN_ONLY,
    HVAC_MODE_DRY,
    HVAC_MODE_OFF,
    PRESET_AWAY,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    PRESET_NONE,
    SUPPORT_FAN_MODE
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, callback
from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.3
DEFAULT_NAME = "Generic Thermostat"

CONF_HEATER = "heater"
CONF_COOLER = "cooler"
CONF_FAN = "fan"
CONF_FAN_BEHAVIOR = "fan_behavior"
CONF_FAN_MODE = "fan_mode"
CONF_DRYER = "dryer"
CONF_DRYER_BEHAVIOR = "dryer_behavior"
CONF_REVERSE_CYCLE = "reverse_cycle"
CONF_SENSOR = "target_sensor"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_MIN_DUR = "min_cycle_duration"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_KEEP_ALIVE = "keep_alive"
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_AWAY_TEMP = "away_temp"
CONF_PRECISION = "precision"
SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE

FAN_MODE_COOL = "cooler"
FAN_MODE_HEAT = "heater"
FAN_MODE_NEUTRAL = "neutral"

FAN_MODE_ON = "on"
FAN_MODE_AUTO = "auto"

DRYER_MODE_COOL = "cooler"
DRYER_MODE_HEAT = "heater"
DRYER_MODE_NEUTRAL = "neutral"

REVERSE_CYCLE_IS_HEATER = "heater"
REVERSE_CYCLE_IS_COOLER = "cooler"
REVERSE_CYCLE_IS_FAN = "fan"
REVERSE_CYCLE_IS_DRYER = "dryer"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HEATER): cv.entity_id,
        vol.Required(CONF_COOLER): cv.entity_id,
        vol.Required(CONF_SENSOR): cv.entity_id,
        vol.Optional(CONF_FAN): cv.entity_id,
        vol.Optional(CONF_FAN_BEHAVIOR, default=FAN_MODE_NEUTRAL): vol.In(
            [FAN_MODE_COOL, FAN_MODE_HEAT, FAN_MODE_NEUTRAL]),
        vol.Optional(CONF_FAN_MODE, default=FAN_MODE_AUTO): vol.In(
            [FAN_MODE_AUTO, FAN_MODE_ON]),
        vol.Optional(CONF_DRYER): cv.entity_id,
        vol.Optional(CONF_DRYER_BEHAVIOR, default=DRYER_MODE_NEUTRAL): vol.In(
            [DRYER_MODE_COOL, DRYER_MODE_HEAT, DRYER_MODE_NEUTRAL]),
        vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
        vol.Optional(CONF_MIN_DUR): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_REVERSE_CYCLE, default=[]): cv.ensure_list_csv,
        vol.Optional(CONF_COLD_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(CONF_HOT_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
        vol.Optional(CONF_KEEP_ALIVE): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(CONF_INITIAL_HVAC_MODE): vol.In(
            [HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_FAN_ONLY, HVAC_MODE_DRY, HVAC_MODE_OFF]
        ),
        vol.Optional(CONF_AWAY_TEMP): vol.Coerce(float),
        vol.Optional(CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the dual mode generic thermostat platform."""
    name = config.get(CONF_NAME)
    heater_entity_id = config.get(CONF_HEATER)
    cooler_entity_id = config.get(CONF_COOLER)
    sensor_entity_id = config.get(CONF_SENSOR)
    fan_entity_id = config.get(CONF_FAN)
    fan_behavior = config.get(CONF_FAN_BEHAVIOR)
    dryer_entity_id = config.get(CONF_DRYER)
    dryer_behavior = config.get(CONF_DRYER_BEHAVIOR)
    reverse_cycle = config.get(CONF_REVERSE_CYCLE)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    min_cycle_duration = config.get(CONF_MIN_DUR)
    cold_tolerance = config.get(CONF_COLD_TOLERANCE)
    hot_tolerance = config.get(CONF_HOT_TOLERANCE)
    keep_alive = config.get(CONF_KEEP_ALIVE)
    initial_hvac_mode = config.get(CONF_INITIAL_HVAC_MODE)
    away_temp = config.get(CONF_AWAY_TEMP)
    precision = config.get(CONF_PRECISION)
    fan_mode = config.get(CONF_FAN_MODE)
    unit = hass.config.units.temperature_unit

    async_add_entities(
        [
            DualModeGenericThermostat(
                name,
                heater_entity_id,
                cooler_entity_id,
                sensor_entity_id,
                fan_entity_id,
                fan_behavior,
                dryer_entity_id,
                dryer_behavior,
                reverse_cycle,
                min_temp,
                max_temp,
                target_temp,
                min_cycle_duration,
                cold_tolerance,
                hot_tolerance,
                keep_alive,
                initial_hvac_mode,
                away_temp,
                precision,
                fan_mode,
                unit,
            )
        ]
    )


class DualModeGenericThermostat(ClimateEntity, RestoreEntity):
    """Representation of a Generic Thermostat device."""

    def __init__(
            self,
            name,
            heater_entity_id,
            cooler_entity_id,
            sensor_entity_id,
            fan_entity_id,
            fan_behavior,
            dryer_entity_id,
            dryer_behavior,
            reverse_cycle,
            min_temp,
            max_temp,
            target_temp,
            min_cycle_duration,
            cold_tolerance,
            hot_tolerance,
            keep_alive,
            initial_hvac_mode,
            away_temp,
            precision,
            fan_mode,
            unit,
    ):
        """Initialize the thermostat."""
        self._name = name
        self.heater_entity_id = heater_entity_id
        self.cooler_entity_id = cooler_entity_id
        self.sensor_entity_id = sensor_entity_id
        self.fan_entity_id = fan_entity_id
        self.fan_behavior = fan_behavior
        self.dryer_entity_id = dryer_entity_id
        self.dryer_behavior = dryer_behavior
        self._fan_mode = fan_mode

        # This part allows previous users of the integration to update seamlessly #
        if reverse_cycle.count(True) == 1:
            self.reverse_cycle = [REVERSE_CYCLE_IS_HEATER, REVERSE_CYCLE_IS_COOLER]
            _LOGGER.warning(
                "Detected legacy config for 'reverse_cycle' | "
                "Please use this in future: "
                "reverse_cycle: heater, cooler"
            )
        elif reverse_cycle.count(False) == 1:
            self.reverse_cycle = []
            _LOGGER.warning(
                "Detected legacy config for 'reverse_cycle' | "
                "Please use leave it empty in future"
            )
        else:
            self.reverse_cycle = reverse_cycle
        # This part allows previous users of the integration to update seamlessly #

        self.min_cycle_duration = min_cycle_duration
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance
        self._keep_alive = keep_alive
        self._hvac_mode = initial_hvac_mode
        self._saved_target_temp = target_temp or away_temp
        self._temp_precision = precision
        self._hvac_list = [HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY, HVAC_MODE_OFF]
        # temp remove fan for debugging
        self._hvac_list.remove(HVAC_MODE_FAN_ONLY)
        if self.cooler_entity_id is None:
            self._hvac_list.remove(HVAC_MODE_COOL)
        if self.heater_entity_id is None:
            self._hvac_list.remove(HVAC_MODE_HEAT)
        if self.fan_entity_id is None:
            self._hvac_list.remove(HVAC_MODE_FAN_ONLY)
        if self.dryer_entity_id is None:
            self._hvac_list.remove(HVAC_MODE_DRY)
        self._fan_mode_list = [FAN_MODE_ON, FAN_MODE_AUTO]
        self._active = False
        self._cur_temp = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temp = target_temp
        self._unit = unit
        self._support_flags = SUPPORT_FLAGS
        if away_temp:
            self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE
        self._away_temp = away_temp
        self._is_away = False

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        async_track_state_change(
            self.hass, self.sensor_entity_id, self._async_sensor_changed
        )
        if self.heater_entity_id is not None:
            async_track_state_change(
                self.hass, self.heater_entity_id, self._async_switch_changed
            )
        if self.cooler_entity_id is not None:
            async_track_state_change(
                self.hass, self.cooler_entity_id, self._async_switch_changed
            )
        # if self.fan_entity_id is not None:
        #     async_track_state_change(
        #         self.hass, self.fan_entity_id, self._async_switch_changed
        #     )
        if self.dryer_entity_id is not None:
            async_track_state_change(
                self.hass, self.dryer_entity_id, self._async_switch_changed
            )

        if self._keep_alive:
            async_track_time_interval(
                self.hass, self._async_control_heating, self._keep_alive
            )

        @callback
        def _async_startup(event):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                    STATE_UNAVAILABLE,
                    STATE_UNKNOWN,
            ):
                self._async_update_temp(sensor_state)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    if self._hvac_mode == HVAC_MODE_COOL:
                        self._target_temp = self.max_temp
                    if self._hvac_mode == HVAC_MODE_FAN_ONLY:
                        self._target_temp = self.max_temp
                    if self._hvac_mode == HVAC_MODE_HEAT:
                        self._target_temp = self.min_temp
                    if self._hvac_mode == HVAC_MODE_DRY:
                        self._target_temp = self._min_temp
                    else:
                        self._target_temp = self.min_temp
                    _LOGGER.warning(
                        "Undefined target temperature," "falling back to %s",
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if old_state.attributes.get(ATTR_PRESET_MODE) == PRESET_AWAY:
                self._is_away = True
            if not self._hvac_mode and old_state.state:
                self._hvac_mode = old_state.state

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                if self._hvac_mode == HVAC_MODE_COOL:
                    self._target_temp = self.max_temp
                if self._hvac_mode == HVAC_MODE_FAN_ONLY:
                    self._target_temp = self.max_temp
                if self._hvac_mode == HVAC_MODE_HEAT:
                    self._target_temp = self.min_temp
                if self._hvac_mode == HVAC_MODE_DRY:
                    self._target_temp = self.min_temp
                else:
                    self._target_temp = self.min_temp
            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._target_temp
            )

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVAC_MODE_OFF

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVAC_MODE_OFF:
            return CURRENT_HVAC_OFF
        if not self._is_device_active:
            return CURRENT_HVAC_IDLE
        if self._hvac_mode == HVAC_MODE_COOL:
            return CURRENT_HVAC_COOL
        if self._hvac_mode == HVAC_MODE_HEAT:
            return CURRENT_HVAC_HEAT
        if self._hvac_mode == HVAC_MODE_FAN_ONLY:
            return CURRENT_HVAC_FAN
        if self._hvac_mode == HVAC_MODE_DRY:
            return CURRENT_HVAC_DRY
        return CURRENT_HVAC_IDLE

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        return PRESET_AWAY if self._is_away else PRESET_NONE

    @property
    def fan_modes(self):
        """List of available operation modes."""
        return self._fan_mode_list

    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._fan_mode

    @property
    def preset_modes(self):
        """Return a list of available preset modes or PRESET_NONE if _away_temp is undefined."""
        return [PRESET_NONE, PRESET_AWAY] if self._away_temp else PRESET_NONE
        
    # def set_fan_mode(self, fan_mode):
    #     """Set the fan mode.  Valid values are "on" or "auto"."""
    #     if fan_mode.lower() not in (FAN_MODE_ON, FAN_MODE_AUTO):
    #         error = "Invalid fan_mode value:  Valid values are 'on' or 'auto'"
    #         _LOGGER.error(error)
    #         return
    #     self._fan_mode = fan_mode
    #     # if fan_mode == FAN_MODE_ON:
    #     #     await self._async_fan_turn_on()
    #     # else:
    #     #     if not self._is_device_active:
    #     #         await self._async_fan_turn_off()
    #     _LOGGER.info("Setting fan mode to: %s", fan_mode)
        
    async def async_set_fan_mode(self, fan_mode) -> None:
        """Set new target fan mode."""
        if fan_mode.lower() not in (FAN_MODE_ON, FAN_MODE_AUTO):
            error = "Invalid fan_mode value:  Valid values are 'on' or 'auto'"
            _LOGGER.error(error)
            return
        self._fan_mode = fan_mode
        if fan_mode == FAN_MODE_ON:
            await self._async_fan_turn_on()
        elif not self._is_device_active:
            await self._async_fan_turn_off()
        else:
            _LOGGER.info("Fan set to auto and will turn off after current cycle completes.")
        _LOGGER.info("Setting fan mode to: %s", fan_mode)
        self.async_write_ha_state()
        return

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        if hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
            if self._is_device_active:
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_COOLER) == 0:
                    await self._async_cooler_turn_off()
                # if self.reverse_cycle.count(REVERSE_CYCLE_IS_FAN) == 0 and self._fan_mode == FAN_MODE_AUTO:
                #     await self._async_fan_turn_off()
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_DRYER) == 0:
                    await self._async_dryer_turn_off()
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_COOL:
            self._hvac_mode = HVAC_MODE_COOL
            if self._is_device_active:
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_HEATER) == 0:
                    await self._async_heater_turn_off()
                # if self.reverse_cycle.count(REVERSE_CYCLE_IS_FAN) == 0 and self._fan_mode == FAN_MODE_AUTO:
                #     await self._async_fan_turn_off()
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_DRYER) == 0:
                    await self._async_dryer_turn_off()
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_FAN_ONLY:
            self._hvac_mode = HVAC_MODE_FAN_ONLY
            if self._is_device_active:
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_COOLER) == 0:
                    await self._async_cooler_turn_off()
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_HEATER) == 0:
                    await self._async_heater_turn_off()
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_DRYER) == 0:
                    await self._async_dryer_turn_off()
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_DRY:
            self._hvac_mode = HVAC_MODE_DRY
            if self._is_device_active:
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_COOLER) == 0:
                    await self._async_cooler_turn_off()
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_HEATER) == 0:
                    await self._async_heater_turn_off()
                if self.reverse_cycle.count(REVERSE_CYCLE_IS_FAN) == 0:
                    await self._async_fan_turn_off()
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_OFF:
            self._hvac_mode = HVAC_MODE_OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
                await self._async_cooler_turn_off()
                if self._fan_mode == FAN_MODE_AUTO:
                    await self._async_fan_turn_off()
                await self._async_dryer_turn_off()
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._target_temp = temperature
        await self._async_control_heating(force=True)
        self.async_write_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp is not None:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp is not None:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    async def _async_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)
        await self._async_control_heating()
        self.async_write_ha_state()

    @callback
    def _async_switch_changed(self, entity_id, old_state, new_state):
        """Handle heater switch state changes."""
        if new_state is None:
            return
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            self._cur_temp = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_control_heating(self, time=None, force=False):
        """Check if we need to turn heating on or off."""
        async with self._temp_lock:
            if not self._active and None not in (self._cur_temp, self._target_temp):
                self._active = True
                _LOGGER.info(
                    "Obtained current and target temperature. "
                    "Generic Dual-mode thermostat active. %s, %s",
                    self._cur_temp,
                    self._target_temp,
                )

            if not self._active or self._hvac_mode == HVAC_MODE_OFF:
                return

            if not force and time is None:
                # If the `force` argument is True, we
                # ignore `min_cycle_duration`.
                # If the `time` argument is not none, we were invoked for
                # keep-alive purposes, and `min_cycle_duration` is irrelevant.
                if self.min_cycle_duration:
                    if self._hvac_mode == HVAC_MODE_COOL:
                        active_entity = self.cooler_entity_id
                    if self._hvac_mode == HVAC_MODE_HEAT:
                        active_entity = self.heater_entity_id
                    if self._hvac_mode == HVAC_MODE_FAN_ONLY:
                        active_entity = self.fan_entity_id
                    if self._hvac_mode == HVAC_MODE_DRY:
                        active_entity = self.dryer_entity_id

                    if self._is_device_active:
                        current_state = STATE_ON
                    else:
                        current_state = HVAC_MODE_OFF
                    long_enough = condition.state(
                        self.hass,
                        active_entity,
                        current_state,
                        self.min_cycle_duration,
                    )
                    if not long_enough:
                        return

            too_cold = self._target_temp >= self._cur_temp + self._cold_tolerance
            too_hot = self._cur_temp >= self._target_temp + self._hot_tolerance
            if self._is_device_active: # when to turn off
                if too_cold and self._hvac_mode == HVAC_MODE_COOL:
                    _LOGGER.info("Turning off cooler %s", self.cooler_entity_id)
                    await self._async_cooler_turn_off()
                elif too_hot and self._hvac_mode == HVAC_MODE_HEAT:
                    _LOGGER.info("Turning off heater %s", self.heater_entity_id)
                    await self._async_heater_turn_off()
                elif self._hvac_mode == HVAC_MODE_FAN_ONLY:
                    if too_cold and self.fan_behavior == FAN_MODE_COOL:
                        _LOGGER.info("Turning off fan %s", self.fan_entity_id)
                        await self._async_fan_turn_off()
                    elif too_hot and self.fan_behavior == FAN_MODE_HEAT:
                        _LOGGER.info("Turning off fan %s", self.fan_entity_id)
                        await self._async_fan_turn_off()
                elif self._hvac_mode == HVAC_MODE_DRY:
                    if too_cold and self.dryer_behavior == DRYER_MODE_COOL:
                        _LOGGER.info("Turning off dehumidifier %s", self.dryer_entity_id)
                        await self._async_dryer_turn_off()
                    elif too_hot and self.dryer_behavior == DRYER_MODE_HEAT:
                        _LOGGER.info("Turning off dehumidifier %s", self.dryer_entity_id)
                        await self._async_dryer_turn_off()
                elif time is not None:
                    # The time argument is passed only in keep-alive case
                    _LOGGER.info(
                        "Keep-alive - Turning on heater %s", active_entity
                    )
                    if self._hvac_mode == HVAC_MODE_COOL:
                        await self._async_cooler_turn_on()
                    elif self._hvac_mode == HVAC_MODE_HEAT:
                        await self._async_heater_turn_on()
                    elif self._hvac_mode == HVAC_MODE_FAN_ONLY:
                        await self._async_fan_turn_on()
                    elif self._hvac_mode == HVAC_MODE_DRY:
                        await self._async_dryer_turn_on()
            else: # when to turn on
                if too_hot and self._hvac_mode == HVAC_MODE_COOL:
                    _LOGGER.info("Turning on cooler %s", self.cooler_entity_id)
                    await self._async_cooler_turn_on()
                elif too_cold and self._hvac_mode == HVAC_MODE_HEAT:
                    _LOGGER.info("Turning on heater %s", self.heater_entity_id)
                    await self._async_heater_turn_on()
                elif self._hvac_mode == HVAC_MODE_FAN_ONLY:
                    if too_hot and self.fan_behavior == FAN_MODE_COOL:
                        _LOGGER.info("Turning on fan %s", self.fan_entity_id)
                        await self._async_fan_turn_on()
                    elif too_cold and self.fan_behavior == FAN_MODE_HEAT:
                        _LOGGER.info("Turning on fan %s", self.fan_entity_id)
                        await self._async_fan_turn_on()
                elif self._hvac_mode == HVAC_MODE_DRY:
                    if too_hot and self.dryer_behavior == DRYER_MODE_COOL:
                        _LOGGER.info("Turning on dehumidifier %s", self.dryer_entity_id)
                        await self._async_dryer_turn_on()
                    elif too_cold and self.dryer_behavior == DRYER_MODE_HEAT:
                        _LOGGER.info("Turning on dehumidifier %s", self.dryer_entity_id)
                        await self._async_dryer_turn_on()
                elif time is not None:
                    # The time argument is passed only in keep-alive case
                    _LOGGER.info(
                        "Keep-alive - Turning off heater %s", active_entity
                    )
                    if self._hvac_mode == HVAC_MODE_COOL:
                        await self._async_cooler_turn_off()
                    elif self._hvac_mode == HVAC_MODE_HEAT:
                        await self._async_heater_turn_off()
                    elif self._hvac_mode == HVAC_MODE_FAN_ONLY:
                        await self._async_fan_turn_off()
                    elif self._hvac_mode == HVAC_MODE_DRY:
                        await self._async_dryer_turn_off()

            if self.fan_behavior == FAN_MODE_NEUTRAL and self._hvac_mode == HVAC_MODE_FAN_ONLY:
                await self._async_fan_turn_on()
            if self.dryer_behavior == DRYER_MODE_NEUTRAL and self._hvac_mode == HVAC_MODE_DRY:
                await self._async_dryer_turn_on()

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        # goes on line 3 below
                    # ([self.fan_entity_id] if self.fan_entity_id else []) + \
        devices = [] + \
            ([self.cooler_entity_id] if self.cooler_entity_id else []) + \
            ([self.heater_entity_id] if self.heater_entity_id else []) + \
            ([self.dryer_entity_id] if self.dryer_entity_id else [])
        device_states = [self.hass.states.is_state(dev, STATE_ON) for dev in devices]
        return next((state for state in device_states if state), False)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags
        
    async def _async_fan_delay_call(self, delay, on):
        """delay toggling the fan on/off."""
        await asyncio.sleep(delay)
        if on == True:
            await self._async_fan_turn_on()
        else:
            await self._async_fan_turn_off()
            
    async def fan_on(self):
        """delay toggling the fan on/off."""
        await asyncio.sleep(5)
        if self._is_device_active:
            await self._async_fan_turn_on()
        
    async def fan_off(self):
        """delay toggling the fan on/off."""
        await asyncio.sleep(5)
        if not self._is_device_active and self._fan_mode == FAN_MODE_AUTO:
            await self._async_fan_turn_off()

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on."""
        if self.heater_entity_id is not None:
            data = {ATTR_ENTITY_ID: self.heater_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_ON, data)
            asyncio.ensure_future(self.fan_on())
            # await self._async_fan_delay_call(5, True)

    async def _async_heater_turn_off(self):
        """Turn heater toggleable device off."""
        if self.heater_entity_id is not None:
            data = {ATTR_ENTITY_ID: self.heater_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_OFF, data)
        if self._fan_mode == FAN_MODE_AUTO:
            asyncio.ensure_future(self.fan_off())
            # await self._async_fan_delay_call(15, False)

    async def _async_cooler_turn_on(self):
        """Turn cooler toggleable device on."""
        if self.cooler_entity_id is not None:
            await self._async_fan_turn_on()
            data = {ATTR_ENTITY_ID: self.cooler_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_ON, data)

    async def _async_cooler_turn_off(self):
        """Turn cooler toggleable device off."""
        if self._fan_mode == FAN_MODE_AUTO:
            await self._async_fan_turn_off()
        if self.cooler_entity_id is not None:
            data = {ATTR_ENTITY_ID: self.cooler_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_OFF, data)

    async def _async_fan_turn_on(self):
        """Turn cooler toggleable device on."""
        if self.fan_entity_id is not None:
            data = {ATTR_ENTITY_ID: self.fan_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_ON, data)

    async def _async_fan_turn_off(self):
        """Turn fan toggleable device off."""
        if self.fan_entity_id is not None:
            data = {ATTR_ENTITY_ID: self.fan_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_OFF, data)

    async def _async_dryer_turn_on(self):
        """Turn cooler toggleable device on."""
        if self.dryer_entity_id is not None:
            data = {ATTR_ENTITY_ID: self.dryer_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_ON, data)

    async def _async_dryer_turn_off(self):
        """Turn fan toggleable device off."""
        if self.dryer_entity_id is not None:
            data = {ATTR_ENTITY_ID: self.dryer_entity_id}
            await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_OFF, data)

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        if preset_mode == PRESET_AWAY and not self._is_away:
            self._is_away = True
            self._saved_target_temp = self._target_temp
            self._target_temp = self._away_temp
            await self._async_control_heating(force=True)
        elif preset_mode == PRESET_NONE and self._is_away:
            self._is_away = False
            self._target_temp = self._saved_target_temp
            await self._async_control_heating(force=True)

        self.async_write_ha_state()
