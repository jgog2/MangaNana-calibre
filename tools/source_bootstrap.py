"""Expose an unpacked checkout under the canonical plugin namespace for tests.

Installed plugins use Calibre's loader; this helper is development-only and does
not create aliases for old flat module names or execute the Calibre entry point.
"""
from importlib.machinery import ModuleSpec
from pathlib import Path
import sys
import types


def ensure_source_package(root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve()
    if 'calibre_plugins.manganana' in sys.modules:
        return
    if 'calibre_plugins' not in sys.modules:
        top=types.ModuleType('calibre_plugins');top.__path__=[]
        top.__spec__=ModuleSpec('calibre_plugins',loader=None,is_package=True)
        sys.modules['calibre_plugins']=top
    module=types.ModuleType('calibre_plugins.manganana')
    module.__file__=str(root/'__init__.py');module.__path__=[str(root)]
    module.__package__=module.__name__
    module.__spec__=ModuleSpec(module.__name__,loader=None,is_package=True)
    module.__spec__.submodule_search_locations=[str(root)]
    sys.modules[module.__name__]=module
    setattr(sys.modules['calibre_plugins'],'manganana',module)


def source_file(name, root=None):
    import json
    root=Path(root or Path(__file__).resolve().parents[1])
    mapping=json.loads((root/"SOURCE_LAYOUT.json").read_text(encoding="utf8"))["files"]
    filename=name if name.endswith(".py") else name+".py"
    return root/mapping.get(filename,filename)
