import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless Qt for the UI tests

import pytest

from dronecalc.core import Assumptions, Build, Constraints, Database, estimate_frame_mass_kg


@pytest.fixture(scope="session")
def db():
    return Database.load(include_custom=False)


@pytest.fixture
def assumptions():
    return Assumptions()


@pytest.fixture
def constraints():
    return Constraints()


@pytest.fixture
def small_build(db):
    """A 10-inch quad: X2212 + 10x4.5 + 4S 5000 mAh + 30 A ESC."""
    prop = db.get("props", "generic-10x4.5")
    return Build(
        motor=db.get("motors", "sunnysky-x2212-980"),
        prop=prop,
        battery=db.get("batteries", "lipo-4s-5000"),
        esc=db.get("escs", "generic-esc-30a-4s"),
        n_rotors=4,
        frame_mass_kg=estimate_frame_mass_kg(prop.diameter_in, 4),
    )
