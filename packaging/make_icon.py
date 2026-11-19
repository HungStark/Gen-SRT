"""Draw the scalable app mark and write Windows icon sizes."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def build_icon():
    root = Path(__file__).resolve().parents[1]
    size = 512
    image = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, 496, 496), radius=104, fill='#132B35')
    draw.rounded_rectangle((45, 45, 467, 467), radius=82, fill='#167968')
    # A subtitle frame around the initial; two caption strokes below it.
    for points in (((99, 189), (99, 124), (166, 124)), ((346, 124), (413, 124), (413, 189)),
                   ((99, 287), (99, 335), (166, 335)), ((346, 335), (413, 335), (413, 287))):
        draw.line(points, fill='#9CE3CD', width=14, joint='curve')
    font = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 232)
    draw.text((256, 221), 'S', font=font, fill='white', anchor='mm')
    draw.rounded_rectangle((122, 379, 390, 394), radius=7, fill='#F4BD4B')
    draw.rounded_rectangle((165, 414, 347, 427), radius=6, fill='#F4BD4B')
    target = root / 'assets/sublens.ico'
    image.save(target, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    image.save(root / 'assets/sublens_icon.png')
    return target


if __name__ == '__main__':
    print(build_icon())
