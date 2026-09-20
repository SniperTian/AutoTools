"""Generate the code-native AutoTools mark (SVG, PNG and multi-size ICO)."""
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = (69, 100, 231)
WHITE = (247, 250, 255)
MINT = (111, 239, 204)
LEFT = [(52, 206), (109, 50), (145, 50), (88, 206)]
RIGHT = [(109, 50), (145, 50), (204, 206), (167, 206)]
ARROW = [(83, 145), (157, 145), (157, 126), (190, 159), (157, 192), (157, 174), (73, 174)]


def inside(x, y, polygon):
    hit = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous; x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2-x1)*(y-y1)/(y2-y1)+x1:
            hit = not hit
        previous = current
    return hit


def pixel(x, y):
    # Rounded tile with transparent corners.
    cx, cy = min(195, max(61, x)), min(195, max(61, y))
    if (x-cx)**2 + (y-cy)**2 > 53**2:
        return (0, 0, 0, 0)
    color = MINT if inside(x, y, ARROW) else WHITE if inside(x, y, LEFT) or inside(x, y, RIGHT) else BACKGROUND
    return (*color, 255)


def png(size):
    raw = bytearray()
    samples = 4
    for y in range(size):
        raw.append(0)
        for x in range(size):
            colors = [pixel((x+(sx+.5)/samples)*256/size, (y+(sy+.5)/samples)*256/size)
                      for sy in range(samples) for sx in range(samples)]
            opaque = [c for c in colors if c[3]]
            if opaque:
                raw.extend([round(sum(c[k] for c in opaque)/len(opaque)) for k in range(3)])
                raw.append(round(255*len(opaque)/len(colors)))
            else:
                raw.extend((0, 0, 0, 0))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind+body))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main():
    assets = ROOT / "assets"; assets.mkdir(exist_ok=True)
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    images = [png(size) for size in sizes]
    offset = 6 + 16*len(sizes)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    for size, image in zip(sizes, images):
        directory.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset))
        offset += len(image)
    (assets / "autotools.ico").write_bytes(directory + b"".join(images))
    (assets / "autotools.png").write_bytes(images[-1])
    shapes = "\n".join(f'<polygon fill="{color}" points="' + " ".join(f"{x},{y}" for x, y in points) + '"/>'
                       for points, color in ((LEFT, "#f7faff"), (RIGHT, "#f7faff"), (ARROW, "#6fefcc")))
    (assets / "autotools.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">\n'
        '<rect x="8" y="8" width="240" height="240" rx="53" fill="#4564e7"/>\n' + shapes + '\n</svg>\n', encoding="utf-8")
    print("AutoTools SVG, PNG and nine-size ICO generated")


if __name__ == "__main__":
    main()
