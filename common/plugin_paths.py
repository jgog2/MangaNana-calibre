"""One filesystem root for unpacked source resources and credential boundaries."""
from pathlib import Path

def plugin_root():
    return Path(__file__).resolve().parents[1]
