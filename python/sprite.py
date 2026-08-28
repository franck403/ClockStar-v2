import framebuf
import gc

HEADER_SIZE = 4
BYTES_PER_PIXEL = 2
MAX_WIDTH = 128

_LINE_BUF = bytearray(MAX_WIDTH * BYTES_PER_PIXEL)
_PAL_BUF = bytearray(4)
_PAL_FB = framebuf.FrameBuffer(_PAL_BUF, 2, 1, framebuf.RGB565)


def peek_size(path):
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
    if len(header) < HEADER_SIZE:
        raise ValueError("Header too short")
    w = header[0] | (header[1] << 8)
    h = header[2] | (header[3] << 8)
    return w, h


def blit_file(
    display,
    path,
    dst_x,
    dst_y,
    key=None,
    darken=None,
    transparent=False,
    palette=None,
):
    if transparent and key is None:
        key = 0

    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            return

        w = header[0] | (header[1] << 8)
        h = header[2] | (header[3] << 8)

        if w > MAX_WIDTH:
            return

        row_bytes = w * BYTES_PER_PIXEL
        mv = memoryview(_LINE_BUF)[:row_bytes]

        for y in range(h):
            if f.readinto(mv) != row_bytes:
                break

            if darken is not None:
                for i in range(0, row_bytes, 2):
                    pixel = (_LINE_BUF[i] << 8) | _LINE_BUF[i + 1]
                    r = int(((pixel >> 11) & 0x1F) * darken)
                    g = int(((pixel >> 5) & 0x3F) * darken)
                    b = int((pixel & 0x1F) * darken)
                    px = (r << 11) | (g << 5) | b
                    _LINE_BUF[i] = (px >> 8) & 0xFF
                    _LINE_BUF[i + 1] = px & 0xFF

            line_fb = framebuf.FrameBuffer(mv, w, 1, framebuf.RGB565)

            cur_y = dst_y + y
            if palette is not None and key is not None:
                display.blit(line_fb, dst_x, cur_y, int(key), palette)
            elif key is not None:
                display.blit(line_fb, dst_x, cur_y, int(key))
            else:
                display.blit(line_fb, dst_x, cur_y)


def write_file(path, width, height, rgb565_bytes):
    header = bytearray(
        [width & 0xFF, (width >> 8) & 0xFF, height & 0xFF, (height >> 8) & 0xFF]
    )
    with open(path, "wb") as f:
        f.write(header)
        f.write(rgb565_bytes)


class IconSet:

    def __init__(self, frames, overlay=None, key=None):
        self.frames = frames
        self.overlay = overlay
        self.key = key

    def draw(
        self,
        display,
        state,
        x,
        y,
        charging=False,
        transparent=False,
        black_overlay=False,
    ):
        path = self.frames.get(state)
        if not path:
            return

        k = 0 if transparent else self.key
        blit_file(display, path, x, y, key=k)

        if charging and self.overlay:
            palette = _PAL_FB if black_overlay else None
            blit_file(display, self.overlay, x, y, key=k, palette=palette)