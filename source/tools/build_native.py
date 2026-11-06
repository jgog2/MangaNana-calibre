"""Build the supplied C kernel with an existing MSVC x64 toolchain only.

No installations or PATH changes. Static CRT, baseline x64 and strict FP;
no /fp:fast, FMA contraction or architecture-specific CPU requirement.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = 'native/windows-x86_64/manganana_dither_abi1.dll'


def build():
    if sys.platform != 'win32': raise RuntimeError('This pass builds Windows x64 only.')
    program_files = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'))
    vswhere = program_files/'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file(): raise RuntimeError('Existing MSVC compiler not found; install nothing automatically.')
    installations = json.loads(subprocess.check_output([
        str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-format', 'json'], text=True))
    if not installations: raise RuntimeError('No installed x64 MSVC compiler.')
    vc = sorted((Path(installations[0]['installationPath'])/'VC/Tools/MSVC').iterdir())[-1]
    sdk = program_files/'Windows Kits/10'
    version = sorted(p.name for p in (sdk/'Include').iterdir() if (sdk/'Lib'/p.name/'ucrt/x64').is_dir())[-1]
    binaries = vc/'bin/Hostx64/x64'
    work = ROOT/'build/native'; work.mkdir(parents=True, exist_ok=True)
    output = ROOT/RESOURCE; output.parent.mkdir(parents=True, exist_ok=True)
    obj = work/'dither_native.obj'
    includes = [vc/'include', *(sdk/'Include'/version/d for d in ('ucrt','shared','um'))]
    subprocess.run([str(binaries/'cl.exe'), '/nologo', '/c', '/O2', '/MT', '/fp:strict', '/W4', '/WX',
                    '/Brepro', '/TC', *(f'/I{p}' for p in includes), f'/Fo{obj}',
                    str(ROOT/'native/dither_native.c')], check=True)
    libs = [vc/'lib/x64', sdk/'Lib'/version/'ucrt/x64', sdk/'Lib'/version/'um/x64']
    subprocess.run([str(binaries/'link.exe'), '/NOLOGO', '/DLL', '/MACHINE:X64', '/Brepro',
                    f'/OUT:{output}', f'/IMPLIB:{work / "manganana_dither.lib"}',
                    *(f'/LIBPATH:{p}' for p in libs), str(obj)], check=True)
    subprocess.run([str(binaries/'dumpbin.exe'), '/DEPENDENTS', str(output)], check=True)
    print(output)


if __name__ == '__main__': build()
