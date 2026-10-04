import pytest

from dronecalc.core import atmosphere, battery_temp_factor, density_altitude_m
from dronecalc.core.constants import RHO0
from dronecalc.core.environment import isa_density, isa_pressure_pa, isa_temperature_k


def test_isa_sea_level():
    assert isa_temperature_k(0) == pytest.approx(288.15)
    assert isa_pressure_pa(0) == pytest.approx(101325.0)
    assert isa_density(0) == pytest.approx(1.225, abs=1e-3)
    assert RHO0 == pytest.approx(1.225, abs=1e-3)


@pytest.mark.parametrize(
    "h, rho, p",
    [(1000, 1.1117, 89874.6), (5000, 0.7364, 54019.9), (11000, 0.3639, 22632.1)],
)
def test_isa_reference_values(h, rho, p):
    assert isa_density(h) == pytest.approx(rho, rel=1e-3)
    assert isa_pressure_pa(h) == pytest.approx(p, rel=1e-3)


def test_stratosphere_is_isothermal():
    assert isa_temperature_k(15000) == pytest.approx(216.65)
    assert isa_density(15000) == pytest.approx(0.19367, rel=1e-3)


def test_density_altitude_roundtrip():
    for h in (0, 500, 3000, 9000, 14000):
        assert density_altitude_m(isa_density(h)) == pytest.approx(h, abs=0.01)


def test_hot_day_raises_density_altitude():
    hot = atmosphere(0, 20.0)
    assert hot.density < RHO0
    assert 600 < hot.density_altitude_m < 900  # ~120 ft per degC


def test_cold_day_lowers_density_altitude():
    assert atmosphere(0, -15.0).density_altitude_m < 0


def test_altitude_out_of_range():
    with pytest.raises(ValueError):
        atmosphere(25000)
    with pytest.raises(ValueError):
        atmosphere(0, -300.0)


def test_battery_temp_factor_interpolates_and_clamps():
    assert battery_temp_factor(25) == 1.0
    assert battery_temp_factor(-40) == pytest.approx(0.65)
    assert battery_temp_factor(5) == pytest.approx(0.915)
    assert battery_temp_factor(-5) < battery_temp_factor(5)
