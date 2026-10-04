"""Physical constants and unit conversions (SI unless stated)."""

import math

G = 9.80665  # m/s^2, standard gravity
R_AIR = 287.05287  # J/(kg K), specific gas constant of dry air

# International Standard Atmosphere (ISA) sea-level values
T0_K = 288.15
P0_PA = 101325.0
LAPSE_K_PER_M = 0.0065
RHO0 = P0_PA / (R_AIR * T0_K)  # ~1.225 kg/m^3

H_TROPOPAUSE_M = 11000.0
H_MIN_M = -2000.0
H_MAX_M = 20000.0

IN_TO_M = 0.0254
G_TO_KG = 1e-3

TWO_PI = 2.0 * math.pi
