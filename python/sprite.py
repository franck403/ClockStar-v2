import framebuf
import micropython
import machine
import gc

HEADER_SIZE = 4
BYTES_PER_PIXEL = 2
MAX_WIDTH = 128
# Reduced from 8 to 2 rows: 128*2*8 = 2048B contiguous was failing to
# allocate on a fragmented heap right after boot (see MemoryError on
# `import sprite`, 936B alloc failing despite ~260KB "free" reported by
# idf_heap_info -- that free memory was in a different region /
# non-contiguous chunks, not usable for one bytearray). 128*2*2 = 512B
# is small enough to fit in the fragmented gaps we actually see at boot.
CHUNK_ROWS = 2

# Lazily allocated instead of at import time. Importing this module no
# longer allocates a large contiguous buffer itself -- the caller (or
# first use of blit_file) triggers allocation, by which point cs.begin()
# and earlier gc.collect() calls have had a chance to compact the heap.
_CHUNK_BUF = None


def _ensure_chunk_buf():
    global _CHUNK_BUF
    if _CHUNK_BUF is None:
        gc.collect()
        try:
            _CHUNK_BUF = bytearray(MAX_WIDTH * BYTES_PER_PIXEL * CHUNK_ROWS)
        except MemoryError:
            # Retry once after a hard collect; if it still fails, let the
            # caller see the MemoryError rather than silently rebooting
            # from inside a library import.
            gc.collect()
            _CHUNK_BUF = bytearray(MAX_WIDTH * BYTES_PER_PIXEL * CHUNK_ROWS)
    return _CHUNK_BUF


def peek_size(path):
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
    if len(header) < HEADER_SIZE:
        raise ValueError("Header short")
    w = header[0] | (header[1] << 8)
    h = header[2] | (header[3] << 8)
    return w, h

@micropython.viper
def fast_fill(buf_in, num_pixels: int, color: int):
    buf32 = ptr32(buf_in)
    hi = (color >> 8) & 255
    lo = color & 255
    c32 = int(hi | (lo << 8) | (hi << 16) | (lo << 24))
    words = num_pixels >> 1
    for i in range(words):
        buf32[i] = c32
    if (num_pixels & 1) != 0:
        buf8 = ptr8(buf_in)
        offset = words << 2
        buf8[offset] = hi
        buf8[offset + 1] = lo

@micropython.viper
def _blit_chunk_viper(dst_buf: ptr8, dst_w: int, src_buf: ptr8, src_w: int, dst_x: int, start_y: int, rows: int, dst_h: int, key_hi: int, key_lo: int, use_key: int, force_color: int, force_hi: int, force_lo: int):
    dst_stride = dst_w << 1
    src_stride = src_w << 1
    
    for ry in range(rows):
        cur_y = start_y + ry
        if cur_y >= 0 and cur_y < dst_h:
            s_off = ry * src_stride
            d_off = (cur_y * dst_stride) + (dst_x << 1)
            
            for x in range(src_w):
                dx = dst_x + x
                if dx >= 0 and dx < dst_w:
                    s = s_off + (x << 1)
                    hi = src_buf[s]
                    lo = src_buf[s + 1]
                    if not (use_key == 1 and hi == key_hi and lo == key_lo):
                        d = d_off + (x << 1)
                        if force_color == 1:
                            dst_buf[d] = force_hi
                            dst_buf[d + 1] = force_lo
                        else:
                            dst_buf[d] = ((lo & 31) << 3) | (hi & 7)
                            dst_buf[d + 1] = (lo & 224) | ((hi & 248) >> 3)

@micropython.viper
def _blit_chunk_rot90cw_viper(dst_buf: ptr8, dst_w: int, src_buf: ptr8, src_w: int, chunk_h: int, dst_x: int, dst_y: int, y_start: int, full_h: int, dst_h: int, key_hi: int, key_lo: int, use_key: int, force_color: int, force_hi: int, force_lo: int):
    # Source chunk is `chunk_h` rows x `src_w` cols, rows y_start..y_start+chunk_h-1 of the
    # full (unrotated) sprite of height `full_h`. Rotating the WHOLE sprite 90 deg CW maps a
    # source pixel (sx, sy_full) -> rotated pixel (rx, ry) = (full_h - 1 - sy_full, sx).
    # So each row of this chunk becomes a COLUMN in the destination, at
    # column index = full_h - 1 - sy_full, offset from dst_x.
    dst_stride = dst_w << 1
    src_stride = src_w << 1

    for ry in range(chunk_h):
        sy_full = y_start + ry
        rot_col = full_h - 1 - sy_full   # column in rotated image for this whole source row
        dx = dst_x + rot_col
        if dx >= 0 and dx < dst_w:
            s_off = ry * src_stride
            d_col_off = dx << 1
            for x in range(src_w):
                # source pixel (x, sy_full) -> rotated row index x -> dest y = dst_y + x
                dy = dst_y + x
                if dy >= 0 and dy < dst_h:
                    s = s_off + (x << 1)
                    hi = src_buf[s]
                    lo = src_buf[s + 1]
                    if not (use_key == 1 and hi == key_hi and lo == key_lo):
                        d = (dy * dst_stride) + d_col_off
                        if force_color == 1:
                            dst_buf[d] = force_hi
                            dst_buf[d + 1] = force_lo
                        else:
                            dst_buf[d] = ((lo & 31) << 3) | (hi & 7)
                            dst_buf[d + 1] = (lo & 224) | ((hi & 248) >> 3)

def blit_file(
    display,
    path,
    dst_x,
    dst_y,
    key=None,
    darken=None,
    transparent=False,
    palette=None,
    rotate90=False,
    offset_x=0,
    offset_y=0,
    force_color=None,   # e.g. 0xFFE0 for yellow, 0x0000 for black, None to disable
):
    if transparent and key is None:
        key = 0

    dst_x += offset_x
    dst_y += offset_y

    has_direct_buf = hasattr(display, "buf") and hasattr(display, "width") and hasattr(display, "height")

    chunk_buf = _ensure_chunk_buf()

    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            return
        w = header[0] | (header[1] << 8)
        h = header[2] | (header[3] << 8)
        if w > MAX_WIDTH:
            return
        
        row_bytes = w * BYTES_PER_PIXEL
        mv = memoryview(chunk_buf)

        use_key = 1 if key is not None else 0
        key_hi = (key >> 8) & 0xFF if use_key else 0
        key_lo = key & 0xFF if use_key else 0

        fc = 1 if force_color is not None else 0
        fc_hi = (force_color >> 8) & 0xFF if fc else 0
        fc_lo = force_color & 0xFF if fc else 0

        if has_direct_buf:
            dst_buf = display.buf
            dst_w = display.width
            dst_h = display.height

            if rotate90:
                # after a 90deg rotation the sprite's footprint on screen is h wide x w tall
                if dst_x >= dst_w or dst_x + h <= 0 or dst_y >= dst_h or dst_y + w <= 0:
                    return
                for y_start in range(0, h, CHUNK_ROWS):
                    rows_to_read = min(CHUNK_ROWS, h - y_start)
                    bytes_to_read = rows_to_read * row_bytes
                    read_len = f.readinto(mv[:bytes_to_read])
                    if read_len == 0:
                        break
                    _blit_chunk_rot90cw_viper(dst_buf, dst_w, chunk_buf, w, rows_to_read, dst_x, dst_y, y_start, h, dst_h, key_hi, key_lo, use_key, fc, fc_hi, fc_lo)
                return

            if dst_x >= dst_w or dst_x + w <= 0 or dst_y >= dst_h or dst_y + h <= 0:
                return

            for y_start in range(0, h, CHUNK_ROWS):
                rows_to_read = min(CHUNK_ROWS, h - y_start)
                bytes_to_read = rows_to_read * row_bytes
                read_len = f.readinto(mv[:bytes_to_read])
                if read_len == 0:
                    break
                
                _blit_chunk_viper(dst_buf, dst_w, chunk_buf, w, dst_x, dst_y + y_start, rows_to_read, dst_h, key_hi, key_lo, use_key, fc, fc_hi, fc_lo)

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
        overlay_color=0x0000,  # default black, pass 0xFFE0 for yellow
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
                rotate90=True,
                offset_x=5,
                offset_y=6,
                force_color=overlay_color if black_overlay else None,
            )

if __name__ == "__main__":
    import Clockstar_v2 as cs
    cs.begin()
    fast_fill(cs.display.buf, cs.display.width * cs.display.height, 0x0000)
    blit_file(cs.display, "clock_bg.spr", 0, 0)
    cs.display.commit()
