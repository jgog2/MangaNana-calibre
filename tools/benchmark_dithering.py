"""Small repeatable benchmark; no image files, network, or dependency installs."""
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from dithering import quantize, _get_accelerator, KERNELS


def main():
    print('Synthetic 420x316, depth=8/channel, strength=100%; seconds/page')
    accelerated=_get_accelerator() is not None
    print('Optional Numba available:',accelerated)
    for mode in ('L','RGB'):
        channels=1 if mode=='L' else 3
        image=Image.frombytes(mode,(420,316),bytes((i*37+i//420)%256 for i in range(420*316*channels)))
        for algorithm in KERNELS:
            start=perf_counter(); expected=quantize(image,8,algorithm,backend='python')
            portable=perf_counter()-start
            line=f'{mode} {algorithm}: Python={portable:.4f}'
            if accelerated:
                start=perf_counter(); actual=quantize(image,8,algorithm,backend='numba')
                cold=perf_counter()-start
                start=perf_counter(); actual=quantize(image,8,algorithm,backend='numba')
                warm=perf_counter()-start
                assert actual.tobytes()==expected.tobytes()
                line+=f', Numba first={cold:.4f}, warm={warm:.4f}, exact parity=True'
            print(line,flush=True)


if __name__=='__main__': main()
