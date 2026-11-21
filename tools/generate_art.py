"""Render our title lettering with the bundled OFL font, then encode ASTC tiles."""
from pathlib import Path
import sys,struct,zlib
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0,'client')
from oot_rando.patching.title_badge import encode_blocks
font=ImageFont.truetype('moteur/ootrr-ap/web/assets/fonts/cinzel-latin-wght-normal.woff2',60)
a=Image.new('RGBA',(610,72))
draw=ImageDraw.Draw(a)
text='ARCHIPELAGO'
box=draw.textbbox((0,0),text,font=font)
draw.text(((610-box[2]+box[0])//2-box[0],(72-box[3]+box[1])//2-box[1]),text,
          font=font,fill=(255,244,207,255),stroke_width=1,stroke_fill=(112,77,27,255))
a=a.crop(a.getbbox())
a.save('assets/wordmark.png')
b=Image.open('assets/icon.png').convert('RGBA')
im=Image.new('RGBA',(708,72))
a.thumbnail((610,72),Image.Resampling.LANCZOS)
b=b.crop(b.getbbox());b.thumbnail((66,66),Image.Resampling.LANCZOS)
left=(708-a.width-b.width-9)//2
im.alpha_composite(b,(left,(72-b.height)//2))
im.alpha_composite(a,(left+b.width+9,(72-a.height)//2))
blocks=encode_blocks(*im.size,im.tobytes())
Path('client/ootrr_triforce/title.tiles').write_bytes(zlib.compress(b''.join(struct.pack('<BB',x,y)+blk for (x,y),blk in sorted(blocks.items())),9))
im.save('assets/badge-preview.png')
