HEADER_SIZE = 4
BYTES_PER_PIXEL = 2
MAX_CHUNK_ROWS = 8


def peek_size(path):
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
    if len(header) < HEADER_SIZE:
        raise ValueError("sprite file too short for header: %s" % path)
    width = header[0] | (header[1] << 8)
    height = header[2] | (header[3] << 8)
    return width, height


def _darken_chunk(buf, nbytes, factor):
    for i in range(0, nbytes, 2):
        hi = buf[i]
        lo = buf[i + 1]
        pixel = (hi << 8) | lo

        r5 = (pixel >> 11) & 0x1F
        g6 = (pixel >> 5) & 0x3F
        b5 = pixel & 0x1F

        r5 = int(r5 * factor)
        g6 = int(g6 * factor)
        b5 = int(b5 * factor)

        pixel = (r5 << 11) | (g6 << 5) | b5
        buf[i] = (pixel >> 8) & 0xFF
        buf[i + 1] = pixel & 0xFF


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
    import framebuf

    if transparent and key is None:
        key = 0

    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            raise ValueError("sprite file too short for header: %s" % path)
        width = header[0] | (header[1] << 8)
        height = header[2] | (header[3] << 8)

        row_bytes = width * BYTES_PER_PIXEL
        chunk_rows = max(1, min(MAX_CHUNK_ROWS, height))
        chunk_buf = bytearray(row_bytes * chunk_rows)

        rows_done = 0
        while rows_done < height:
            rows_this_chunk = min(chunk_rows, height - rows_done)
            nbytes = row_bytes * rows_this_chunk

            if rows_this_chunk == chunk_rows:
                mv = memoryview(chunk_buf)
            else:
                mv = memoryview(chunk_buf)[:nbytes]

            got = f.readinto(mv)
            if got != nbytes:
                raise ValueError(
                    "sprite file truncated: %s (wanted %d bytes, got %d)"
                    % (path, nbytes, got)
                )

            chunk_bytes = bytearray(mv)
            if darken is not None:
                _darken_chunk(chunk_bytes, nbytes, darken)

            chunk_fb = framebuf.FrameBuffer(
                chunk_bytes, width, rows_this_chunk, framebuf.RGB565
            )

            if key is not None and palette is not None:
                display.blit(chunk_fb, dst_x, dst_y + rows_done, key, palette)
            elif key is not None:
                display.blit(chunk_fb, dst_x, dst_y + rows_done, key)
            else:
                display.blit(chunk_fb, dst_x, dst_y + rows_done)

            rows_done += rows_this_chunk


def write_file(path, width, height, rgb565_bytes):
    if width <= 0 or height <= 0:
        raise ValueError("width/height must be positive")
    if width > 65535 or height > 65535:
        raise ValueError("width/height must fit in u16")
    if width > 128 or height > 128:
        raise ValueError("sprite exceeds 128x128 cap: %dx%d" % (width, height))

    expected = width * height * BYTES_PER_PIXEL
    if len(rgb565_bytes) != expected:
        raise ValueError(
            "pixel data is %d bytes, expected %d for %dx%d RGB565"
            % (len(rgb565_bytes), expected, width, height)
        )

    header = bytearray(HEADER_SIZE)
    header[0] = width & 0xFF
    header[1] = (width >> 8) & 0xFF
    header[2] = height & 0xFF
    header[3] = (height >> 8) & 0xFF

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
        import framebuf

        path = self.frames.get(state)
        if path is None:
            return
        key = 0 if transparent else self.key
        blit_file(display, path, x, y, key=key)
        if charging and self.overlay:
            palette = None
            if black_overlay:
                pal_buf = bytearray(4)
                pal_buf[0] = 0x00
                pal_buf[1] = 0x00
                pal_buf[2] = 0x00
                pal_buf[3] = 0x00
                palette = framebuf.FrameBuffer(pal_buf, 2, 1, framebuf.RGB565)
            blit_file(display, self.overlay, x, y, key=key, palette=palette)