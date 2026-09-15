"""Build the Windows ICO from the same simple geometry as ui/icon.svg (Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw

scale = 8
im = Image.new('RGBA', (40 * scale, 40 * scale))
d = ImageDraw.Draw(im)
def box(values): return tuple(round(v * scale) for v in values)
blue = '#0067b1'
d.rounded_rectangle(box((0, 0, 40, 40)), radius=10 * scale, fill=blue)
d.ellipse(box((15, 12, 27, 24)), fill='white')
d.rectangle(box((11, 12, 21, 24)), fill='white')
d.rectangle(box((11, 12, 17, 30)), fill='white')
d.ellipse(box((20, 17, 22, 19)), fill=blue)
d.rectangle(box((17, 17, 21, 19)), fill=blue)
d.ellipse(box((26, 26, 32, 32)), fill='#82c8ef')
im.save(Path(__file__).resolve().parents[1] / 'ui/icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
