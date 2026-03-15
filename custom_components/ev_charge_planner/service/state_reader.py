"""Abstraction for reading HA entity states."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StateReader(Protocol):
    """Protocol for reading entity state values.

    Decouples Hub from hass.states.get() so it can be tested
    without a full HA mock.
    """

    def get_state(self, entity_id: str) -> str | None:
        """Return the state string for an entity, or None if unavailable."""
        ...


class HassStateReader:
    """Default implementation backed by hass.states."""

    def __init__(self, hass) -> None:
        self._hass = hass

    def get_state(self, entity_id: str) -> str | None:
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        return state.state
