"""Frame mass model: regression on wheelbase and arm count, with a user override.

``mass_g = K * wheelbase_mm**1.5 * (N / 4)**0.85`` is calibrated to typical carbon-fibre
multirotor frames (roughly 130 g at 220 mm, 380 g at 450 mm, 660 g at 650 mm, 1.3 kg at 1000 mm
for a quad). It is a coarse preliminary-design estimate; pass an explicit mass to override it.
"""

from __future__ import annotations

import math

from dronecalc.core.constants import IN_TO_M

FRAME_MASS_COEFF = 0.040
FRAME_MASS_EXPONENT = 1.5
ARM_COUNT_EXPONENT = 0.85


def wheelbase_mm(prop_diameter_in: float, n_rotors: int, clearance: float = 0.10) -> float:
    """Motor-to-opposite-motor distance so adjacent props keep ``clearance`` * D between tips."""
    adjacent_spacing_m = prop_diameter_in * IN_TO_M * (1.0 + clearance)
    return 1000.0 * adjacent_spacing_m / math.sin(math.pi / n_rotors)


def frame_mass_g(wheelbase: float, n_rotors: int) -> float:
    if wheelbase <= 0:
        raise ValueError("wheelbase must be positive")
    return (
        FRAME_MASS_COEFF * wheelbase**FRAME_MASS_EXPONENT * (n_rotors / 4.0) ** ARM_COUNT_EXPONENT
    )


def estimate_frame_mass_kg(
    prop_diameter_in: float,
    n_rotors: int,
    clearance: float = 0.10,
    override_g: float | None = None,
) -> float:
    if override_g is not None:
        return override_g / 1000.0
    return frame_mass_g(wheelbase_mm(prop_diameter_in, n_rotors, clearance), n_rotors) / 1000.0
