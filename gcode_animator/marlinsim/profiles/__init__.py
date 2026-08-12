"""Printer display profiles for MarlinSIM.

Each profile defines the display geometry and capabilities for a specific
printer/board combination. Profiles are registered in this module.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .base import PrinterProfile
from .ender3v2 import Ender3V2Profile

# Registry of available profiles
_PROFILES: Dict[str, PrinterProfile] = {}


def register_profile(profile: PrinterProfile):
    """Register a printer profile."""
    _PROFILES[profile.name.lower()] = profile


def get_profile(name: str) -> PrinterProfile:
    """Get a printer profile by name.

    Raises:
        KeyError: If profile not found
    """
    key = name.lower()
    if key not in _PROFILES:
        raise KeyError(f"Unknown profile: {name}")
    return _PROFILES[key]


def list_profiles() -> List[Tuple[str, str]]:
    """List all available profiles as (name, description) tuples."""
    return [(p.name, p.description) for p in _PROFILES.values()]


# Register built-in profiles
register_profile(Ender3V2Profile())
