import framebuf
import gc
import esp32

HEADER_SIZE = 4
BYTES_PER_PIXEL = 2
MAX_WIDTH = 128

print("before allcating rendering buffer", esp32.idf_heap_info(esp32.HEAP_DATA))
_LINE_BUF = bytearray(MAX_WIDTH * BYTES_PER_PIXEL)
_LINE_FB = framebuf.FrameBuffer(_LINE_BUF, MAX_WIDTH, 1, framebuf.RGB565)
print("after allcating rendering buffer", esp32.idf_heap_info(esp32.HEAP_DATA))

def peek_size(path):
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
    if len(header) < HEADER_SIZE:
        raise ValueError("Header short")
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

            cur_y = dst_y + y

            if darken is not None:
                for i in range(0, row_bytes, 2):
                    pixel = (_LINE_BUF[i] << 8) | _LINE_BUF[i + 1]
                    r = int(((pixel >> 11) & 0x1F) * darken)
                    g = int(((pixel >> 5) & 0x3F) * darken)
                    b = int((pixel & 0x1F) * darken)
                    px = (r << 11) | (g << 5) | b
                    _LINE_BUF[i] = (px >> 8) & 0xFF
                    _LINE_BUF[i + 1] = px & 0xFF

            if palette is not None:
                for i in range(0, row_bytes, 2):
                    _LINE_BUF[i] = 0
                    _LINE_BUF[i + 1] = 0

            if key is not None:
                key_hi = (key >> 8) & 0xFF
                key_lo = key & 0xFF
                start_x = None

                for x_idx in range(w):
                    i = x_idx * 2
                    is_key = _LINE_BUF[i] == key_hi and _LINE_BUF[i + 1] == key_lo

                    if not is_key:
                        if start_x is None:
                            start_x = x_idx
                    else:
                        if start_x is not None:
                            run_len = x_idx - start_x
                            sub_buf = memoryview(_LINE_BUF)[
                                start_x * 2 : x_idx * 2
                            ]
                            sub_fb = framebuf.FrameBuffer(
                                sub_buf, run_len, 1, framebuf.RGB565
                            )
                            display.blit(sub_fb, dst_x + start_x, cur_y)
                            start_x = None

                if start_x is not None:
                    run_len = w - start_x
                    sub_buf = memoryview(_LINE_BUF)[start_x * 2 : row_bytes]
                    sub_fb = framebuf.FrameBuffer(
                        sub_buf, run_len, 1, framebuf.RGB565
                    )
                    display.blit(sub_fb, dst_x + start_x, cur_y)
            else:
                if w == MAX_WIDTH:
                    display.blit(_LINE_FB, dst_x, cur_y)
                else:
                    line_fb = framebuf.FrameBuffer(mv, w, 1, framebuf.RGB565)
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
            blit_file(
                display,
                self.overlay,
                x,
                y,
                key=k,
                palette=True if black_overlay else None,
            )