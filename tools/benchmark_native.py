"""Serial full-page comparison in Python or calibre-debug; no concurrency/I/O."""
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from dithering import quantize
from native_dithering import ALG_IDS, get_backend


def main():
    if get_backend() is None: raise RuntimeError('Native benchmark requires the validated x64 build')
    print('1680x1264; 8 levels/channel; 100% strength; serial seconds/page; full wrapper included',flush=True)
    for mode,channels in [('L',1),('RGB',3)]:
        im=Image.frombytes(mode,(1680,1264),bytes((i*37+i//1680*13)%256 for i in range(1680*1264*channels)))
        for algorithm in ALG_IDS:
            start=perf_counter(); expected=quantize(im,8,algorithm,backend='python'); portable=perf_counter()-start
            timings=[]
            for _ in range(3):
                start=perf_counter(); result=quantize(im,8,algorithm,backend='native'); timings.append(perf_counter()-start)
                assert expected.tobytes()==result.tobytes()
            accelerated=sorted(timings)[1]
            print(f'{mode} {algorithm}: Python={portable:.6f}, Native median={accelerated:.6f}, speedup={portable/accelerated:.2f}x, parity=exact',flush=True)


if __name__=='__main__': main()
