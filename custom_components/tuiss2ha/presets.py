"""Position presets mixin for Tuiss Smartview BLE blinds."""
from __future__ import annotations

import logging

from homeassistant.exceptions import HomeAssistantError

from .const import ConnectionTimeout, DeviceNotFound

_LOGGER = logging.getLogger(__name__)


class TuissPresetsMixin:
    """Mixin providing HA-side software position presets."""

    async def async_load_presets(self) -> None:
        """Load stored position presets; fall back to empty on corruption."""
        try:
            stored = await self._presets_store.async_load()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "%s: Failed to load presets from storage (%s); starting empty",
                self.name,
                exc,
            )
            self.presets = {}
            return

        if stored and isinstance(stored, dict):
            clean: dict[str, float] = {}
            for name, position in stored.items():
                if not isinstance(name, str) or not name.strip():
                    _LOGGER.warning(
                        "%s: Dropping preset with invalid name %r",
                        self.name,
                        name,
                    )
                    continue
                try:
                    pos_f = float(position)
                except (TypeError, ValueError):
                    _LOGGER.warning(
                        "%s: Dropping preset %r with invalid position %r",
                        self.name,
                        name,
                        position,
                    )
                    continue
                if not 0 <= pos_f <= 100:
                    _LOGGER.warning(
                        "%s: Dropping preset %r with out-of-range position %s",
                        self.name,
                        name,
                        pos_f,
                    )
                    continue
                clean[name] = pos_f
            self.presets = clean
            # Re-persist if we dropped anything so the next restart is clean.
            if len(clean) != len(stored):
                await self._presets_store.async_save(clean)
        else:
            self.presets = {}

    async def async_save_presets(self) -> None:
        """Persist position presets to storage."""
        await self._presets_store.async_save(self.presets)

    async def async_apply_preset(self, name: str) -> None:
        """Move the blind to the position stored under ``name``."""
        if name not in self.presets:
            raise HomeAssistantError(f"{self.name}: preset {name!r} not found")
        position = float(self.presets[name])
        current = self._current_cover_position
        if current is None:
            raise HomeAssistantError(
                f"{self.name}: preset {name!r} cannot apply — current "
                "position is unknown. Move the blind once so its "
                "position is read, then try again."
            )
        movement_direction = 1 if current <= position else -1
        try:
            await self.async_move_cover(
                movement_direction=movement_direction,
                target_position=100 - position,
            )
        except (ConnectionTimeout, DeviceNotFound, HomeAssistantError) as e:
            raise HomeAssistantError(
                f"{self.name}: preset {name!r} failed to apply: {e}"
            ) from e
        _LOGGER.info(
            "%s: Applied preset %r -> %s%%", self.name, name, position
        )

    async def async_save_current_as_preset(self, name: str) -> float | None:
        """Save the live cover position under ``name``."""
        if not isinstance(name, str):
            raise ValueError("preset name must be a string")
        name = name.strip()
        if not name:
            raise ValueError("preset name cannot be empty or whitespace only")
        current = self._current_cover_position
        if current is None:
            _LOGGER.warning(
                "%s: Cannot save preset %r — current position is unknown",
                self.name,
                name,
            )
            return None
        # Clamp against transient out-of-range frames.
        position = max(0.0, min(100.0, float(current)))
        self.presets[name] = position
        await self.async_save_presets()
        self.publish_updates()
        _LOGGER.info(
            "%s: Saved preset %r at current position %s%%",
            self.name,
            name,
            position,
        )
        return position
