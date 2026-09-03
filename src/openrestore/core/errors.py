"""Domain exceptions. Drivers and core components raise these instead of
letting vendor library exceptions (socket errors, HTTP errors, ...) leak
above the layer that knows how to handle them."""

from __future__ import annotations


class OpenRestoreError(Exception):
    """Base class for all domain errors."""


class DeviceUnreachable(OpenRestoreError):
    """A driver could not reach its device (light, audio output, or input)."""


class ConfigError(OpenRestoreError):
    """A config file (routine, curve, device binding) failed validation."""


class UnsafeClock(OpenRestoreError):
    """Neither NTP nor an RTC has provided a trustworthy time this boot."""


class RoutineError(OpenRestoreError):
    """A routine run hit an invalid state transition or a structural problem
    only detectable at run time (e.g. an `at_offset` step with no trigger)."""
