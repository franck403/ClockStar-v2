"""screens.py -- tiny screen / extension API for the Clockstar v2 firmware.

Adding a new screen is one function. Write a module (e.g. ext_hello.py),
give it a register(api) function, and add its module name to
extensions.json (the web installer does that for you, see
python/extensions/manifest.json).

    # ext_hello.py
    def register(api):
        ctx = api.ctx

        def draw():
            ctx.draw_background()
            ctx.draw_header("HELLO")
            ctx.display.text("Hi!", 4, 40, ctx.Color.White)
            ctx.draw_footer_hint("SEL click")

        def on_select():
            print("clicked")

        api.add_screen("Hello", draw, on_select=on_select)

That is the whole thing: the screen shows up in the UP/DOWN cycle after
Clock / Media / Notifs. Pass in_settings=True to list it as a row in
Settings instead (SEL opens it, BACK returns to Settings).

add_screen(name, draw, ...) callbacks (all optional, all take no args
except tick/background which receive time.ticks_ms()):

    draw()            paint the screen (display.commit() is done for you)
    on_up()           UP pressed        |  return False to let the firmware
    on_down()         DOWN pressed      |  handle the press itself (UP/DOWN
    on_select()       SEL short press   |  then cycle screens, BACK leaves);
    on_back()         BACK pressed      |  any other return value = handled
    tick(now)         while the screen is on display, ~every 20ms; return
                      True to request a redraw
    background(now)   every main-loop tick, even when the screen is not
                      displayed or the backlight is off (step counting, ...)
    on_enter()        the screen just became active
    on_exit()         the screen is being left
    veille_exempt     True = the backlight never times out on this screen
    order             sort position among extension screens (default 100)

ctx (api.ctx) gives you: display, Color, WIDTH, HEIGHT, cs, link, piezo,
draw_background(), draw_header(title, badge=True), draw_footer_hint(text),
draw_progress_bar(x, y, w, h, frac), text_2x(s, x, y, color),
truncate(s, max_chars), wrap_text(s, max_chars), mark_dirty(),
buttons.state(ctx.Buttons.Up / Down / Select / Back) -> True while that
button is held down (use it in tick/background for hold-to-repeat).

A callback that raises is caught and printed; it never takes the watch
down. A background() that raises is switched off.
"""

import sys
import json

cycle = []           # screens reachable with UP/DOWN (after the core ones)
settings_pages = []  # screens listed as rows in Settings


class Screen:
    def __init__(self, name, draw):
        self.name = name
        self.draw = draw
        self.on_up = None
        self.on_down = None
        self.on_select = None
        self.on_back = None
        self.tick = None
        self.background = None
        self.on_enter = None
        self.on_exit = None
        self.veille_exempt = False
        self.in_settings = False
        self.order = 100


class _Ctx:
    pass


ctx = _Ctx()


def setup(**kw):
    """Called once by main.py to fill ctx with the shared helpers."""
    for k, v in kw.items():
        setattr(ctx, k, v)


def add_screen(name, draw, on_up=None, on_down=None, on_select=None,
               on_back=None, tick=None, background=None, on_enter=None,
               on_exit=None, veille_exempt=False, in_settings=False,
               order=100):
    scr = Screen(name, draw)
    scr.on_up = on_up
    scr.on_down = on_down
    scr.on_select = on_select
    scr.on_back = on_back
    scr.tick = tick
    scr.background = background
    scr.on_enter = on_enter
    scr.on_exit = on_exit
    scr.veille_exempt = veille_exempt
    scr.in_settings = in_settings
    scr.order = order
    target = settings_pages if in_settings else cycle
    target.append(scr)
    target.sort(key=lambda s: s.order)
    return scr


def run_background(now):
    for lst in (cycle, settings_pages):
        for scr in lst:
            fn = scr.background
            if fn is None:
                continue
            try:
                fn(now)
            except Exception as e:
                sys.print_exception(e)
                print("screens: background of", scr.name, "disabled")
                scr.background = None


def load_extensions(path="extensions.json"):
    """Import every module named in extensions.json and call its
    register(api). Returns the list of modules that loaded."""
    try:
        with open(path, "r") as f:
            names = json.load(f)
    except (OSError, ValueError):
        return []

    api = sys.modules[__name__]
    loaded = []
    for name in names:
        try:
            mod = __import__(name)
            mod.register(api)
            loaded.append(name)
        except Exception as e:
            sys.print_exception(e)
            print("screens: extension failed:", name)
        try:
            import gc
            gc.collect()
        except Exception:
            pass
    return loaded
