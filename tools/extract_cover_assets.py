"""Export the three static MangaAnkā layers from the user-supplied PSD.

Development only: requires psd-tools; the plugin runtime needs only Pillow.
Usage: python tools/extract_cover_assets.py path/to/reference.psd
"""
import argparse
from pathlib import Path


def extract(psd_path):
    from PIL import Image
    from psd_tools import PSDImage

    psd = PSDImage.open(psd_path)
    if psd.size != (880, 1200):
        raise ValueError('Expected the 880 × 1200 reference PSD.')
    layers = {layer.name: layer for layer in psd.descendants()}
    destination = Path(__file__).resolve().parents[1] / 'assets' / 'covers'
    destination.mkdir(parents=True, exist_ok=True)
    for name, filename, bounds in (
        ('Generated Cover Background', 'background.png', (0, 0, 880, 1200)),
        ('Anchor Watermark', 'anchor.png', (123, 437, 619, 1114)),
        ('MangaAnkā Stamp', 'stamp.png', (740, -1, 881, 1201)),
    ):
        layer = layers[name]
        if layer.bbox != bounds:
            raise ValueError(f'{name} geometry changed: {layer.bbox}')
        image = layer.topil().convert('RGBA')
        if filename == 'stamp.png':
            canvas = Image.new('RGBA', psd.size)
            canvas.paste(image, layer.offset)
            image = canvas.crop((740, 0, 880, 1200))
        image.save(destination / filename)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('psd', type=Path)
    extract(parser.parse_args().psd)
