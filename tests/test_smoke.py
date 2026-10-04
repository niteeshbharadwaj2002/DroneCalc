from dronecalc import __version__
from dronecalc.config import DATA_DIR, ROOT_DIR


def test_version():
    assert __version__


def test_paths_exist():
    assert ROOT_DIR.is_dir()
    assert DATA_DIR.is_dir()
