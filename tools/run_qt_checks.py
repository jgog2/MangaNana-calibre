"""Run a Qt smoke script with assertions enabled in Calibre's optimized Python.

Usage: calibre-debug -e tools/run_qt_checks.py -- tools/judgement_qt_smoke.py
"""
from pathlib import Path
import sys

script = Path(sys.argv[-1]).resolve()
namespace = {'__name__': '__main__', '__file__': str(script)}
exec(compile(script.read_bytes(), str(script), 'exec', optimize=0), namespace)
