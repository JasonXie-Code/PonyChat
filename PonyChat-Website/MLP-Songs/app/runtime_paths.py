"""External mutable data roots; source modules and signed inputs stay separate."""
import os
from pathlib import Path


def data_root():
    return Path(os.environ.get('MLP_DATA_ROOT', str(Path(__file__).resolve().parent / 'data')))


def registration_path(path):
    path = Path(path)
    original = Path(__file__).resolve().parent / 'data/follow-catalog.json'
    if path.absolute() == original.absolute():
        return data_root() / 'follow-catalog.json'
    return path
