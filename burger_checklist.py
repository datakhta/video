#!/usr/bin/env python3
"""Animated burger checklist + chomper finale for a vertical video.

Each item gets ticked the moment that ingredient lands on the burger; at the
end either a round chomper eats the burger (--finale chomper, default) or the
FISH&MORE pack pops in with a "Попробуйте!" call to action (--finale pack).
Usage: python3 burger_checklist.py [--finale chomper|pack] [--theme red|blue] INPUT.mov OUTPUT.mp4
"""
import math
import os
import random
import subprocess
import sys
from multiprocessing import Pool

import numpy as np

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from recolor import Recolor

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
SS = 2
FPS = 30

TITLE = "Бургер с котлетой Эби Кацу"
# (text, check time in seconds) — times found frame by frame in the source
ITEMS = [
    ("булка", 0.30),
    ("листья салата", 0.90),
    ("лук", 1.80),
    ("авокадо", 2.40),
    ("котлета эби кацу от FISH&MORE", 2.90),
    ("огурец", 3.30),
    ("помидор", 4.50),
    ("соус", 5.00),
    ("булка", 5.40),
    ("наслаждаемся!", 6.20),
]
CARD_IN = (0.0, 0.3)       # start, duration
CARD_OUT = (16.4, 0.5)     # burger drives up into the card area after ~17 s

FONT = os.path.join(HERE, "fonts", "Nunito.ttf")

WHITE = (255, 255, 255)
WINE = (110, 8, 30)        # picked from the red wall
MUSTARD = (255, 204, 64)   # like the burger sauce
SKY = (141, 198, 232)      # FISH&MORE light blue
NAVY = (14, 58, 93)        # FISH&MORE dark blue
DEEP_BLUE = (28, 88, 175)  # new floor colour

# colour themes: "red" keeps the original set, "blue" repaints it in brand colours
THEMES = {
    "red": dict(backdrop=None, tick=WINE, title=MUSTARD, glass=(WHITE, 22), ink_shadow=(40, 0, 10),
                cta=MUSTARD, cta_shadow=WINE),
    "blue": dict(backdrop=(SKY, DEEP_BLUE), tick=NAVY, title=WHITE, glass=(NAVY, 70), ink_shadow=(4, 24, 48),
                 cta=WHITE, cta_shadow=NAVY),
}
THEME = THEMES["red"]
BLUR = 22                  # frosted-glass blur radius

# layout (1x px)
CARD_X, CARD_Y, CARD_W = 40, 56, W - 80
PAD = 30
TITLE_SIZE, TEXT_SIZE = 48, 31
BOX, GAP, LINE_H, ROW_GAP, COL_GAP = 36, 14, 40, 12, 24
ROWS = 5

# chomper finale. The camera is static and the burger is cut out of the shot at
# 19.05 s, so a frame after that is a clean plate to reveal behind the chomper.
CLEAN_PLATE_T = 19.6
CH_R = 240
CH_X0_T, CH_X0, CH_SPEED = 18.0, 317, 460       # centre x at t, px/s
CH_Y_KEYS = [(16.5, 690), (17.5, 670), (18.0, 610), (18.5, 545), (21.0, 545)]
CH_MOUTH_HZ = 3.2
REVEAL_Y = (320, 920)
FEATHER = 90


def s(v):
    return int(round(v * SS))


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def prog(t, start, dur):
    return ease_out((t - start) / dur)


def font(size, weight):
    f = ImageFont.truetype(FONT, s(size))
    f.set_variation_by_name(weight)
    return f


def wrap(text, f, width):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if f.getlength(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


title_font = font(TITLE_SIZE, b"Black")
text_font = font(TEXT_SIZE, b"ExtraBold")

col_w = (CARD_W - 2 * PAD - COL_GAP) / 2
text_w = col_w - BOX - GAP

# two columns, rows aligned across columns
wrapped = [wrap(txt, text_font, s(text_w)) for txt, _ in ITEMS]
layout = [None] * len(ITEMS)
y = CARD_Y + PAD + TITLE_SIZE + 22
for r in range(ROWS):
    idx = [i for i in (r, r + ROWS) if i < len(ITEMS)]
    for c, i in enumerate(idx):
        layout[i] = (CARD_X + PAD + c * (col_w + COL_GAP), y)
    y += max(len(wrapped[i]) for i in idx) * LINE_H + ROW_GAP
CARD_H = y - ROW_GAP + PAD - CARD_Y
TOP_H = CARD_Y + CARD_H + 20


def draw_check(d, cx, cy, k, al):
    pts = [(cx - 9, cy + 1), (cx - 2, cy + 8), (cx + 10, cy - 8)]
    l1 = math.dist(pts[0], pts[1])
    l2 = math.dist(pts[1], pts[2])
    L = (l1 + l2) * k
    path = [pts[0]]
    if L <= l1:
        f = L / l1
        path.append((pts[0][0] + (pts[1][0] - pts[0][0]) * f, pts[0][1] + (pts[1][1] - pts[0][1]) * f))
    else:
        f = (L - l1) / l2
        path += [pts[1], (pts[1][0] + (pts[2][0] - pts[1][0]) * f, pts[1][1] + (pts[2][1] - pts[1][1]) * f)]
    d.line([(s(x), s(y)) for x, y in path], fill=THEME["tick"] + (al,), width=s(5), joint="curve")
    for x, y in (path[0], path[-1]):
        d.ellipse((s(x - 2.5), s(y - 2.5), s(x + 2.5), s(y + 2.5)), fill=THEME["tick"] + (al,))


def card_alpha(t):
    # linear fade in/out
    a_in = min(max((t - CARD_IN[0]) / CARD_IN[1], 0), 1)
    a_out = min(max((t - CARD_OUT[0]) / CARD_OUT[1], 0), 1)
    return a_in * (1 - a_out)


# static rounded mask for the blurred-background "glass"
GLASS_MASK = Image.new("L", (s(CARD_W), s(CARD_H)), 0)
ImageDraw.Draw(GLASS_MASK).rounded_rectangle((0, 0, s(CARD_W) - 1, s(CARD_H) - 1), s(30), fill=255)
GLASS_MASK = GLASS_MASK.resize((CARD_W, CARD_H), Image.LANCZOS)


def render_card(t, out):
    a = card_alpha(t)
    if a <= 0:
        return
    al = int(255 * a)

    # glass: just a faint tint, no rim (the blur is done in process_frame)
    glass = Image.new("RGBA", (W, TOP_H), (0, 0, 0, 0))
    tint_rgb, tint_a = THEME["glass"]
    tint = Image.new("RGBA", (CARD_W, CARD_H), tint_rgb + (0,))
    tint.putalpha(GLASS_MASK.point(lambda v: int(v * tint_a / 255 * a)))
    glass.alpha_composite(tint, (CARD_X, CARD_Y))

    # content on its own layer so it gets a soft shadow for legibility
    ink = Image.new("RGBA", (s(W), s(TOP_H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(ink)
    d.text((s(CARD_X + PAD), s(CARD_Y + PAD)), TITLE, font=title_font, fill=THEME["title"] + (al,), anchor="lt")
    for (txt, t_chk), lines, (x, y) in zip(ITEMS, wrapped, layout):
        fill = prog(t, t_chk, 0.18)
        check = prog(t, t_chk + 0.08, 0.25)
        pop = 1 + 0.2 * max(0.0, 1 - abs((t - t_chk - 0.12) / 0.12)) if t >= t_chk else 1
        cx, cy = x + BOX / 2, y + LINE_H / 2
        h = BOX / 2 * pop
        box = (s(cx - h), s(cy - h), s(cx + h), s(cy + h))
        d.rounded_rectangle(box, s(10), outline=WHITE + (al,), width=s(3.5))
        if fill > 0:
            d.rounded_rectangle(box, s(10), fill=WHITE + (int(al * fill),), outline=WHITE + (al,), width=s(3.5))
        if check > 0:
            draw_check(d, cx, cy, check, al)
        for k, ln in enumerate(lines):
            d.text((s(x + BOX + GAP), s(y + k * LINE_H + LINE_H / 2)), ln, font=text_font,
                   fill=WHITE + (al,), anchor="lm")

    ink = ink.resize((W, TOP_H), Image.LANCZOS)
    sh = Image.new("RGBA", ink.size, THEME["ink_shadow"] + (0,))
    sh.putalpha(ink.getchannel("A").point(lambda v: v * 0.6).filter(ImageFilter.GaussianBlur(4)))
    out.alpha_composite(glass, (0, 0))
    out.alpha_composite(sh, (0, 2))
    out.alpha_composite(ink, (0, 0))


# --- chomper -----------------------------------------------------------------

def chomper_pos(t):
    x = CH_X0 + CH_SPEED * (t - CH_X0_T)
    keys = CH_Y_KEYS
    if t <= keys[0][0]:
        y = keys[0][1]
    else:
        y = keys[-1][1]
        for (t0, y0), (t1, y1) in zip(keys, keys[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0)
                k = k * k * (3 - 2 * k)
                y = y0 + (y1 - y0) * k
                break
    return x, y


CH_T_START = CH_X0_T - (CH_X0 + CH_R + 40) / CH_SPEED
CH_T_END = CH_X0_T + (W + CH_R + 40 - CH_X0) / CH_SPEED

# crumbs thrown back while it is biting through the burger
rng = random.Random(7)
CRUMB_COLORS = [(214, 150, 72), (196, 128, 56), (128, 186, 64), (246, 196, 60), (240, 236, 224)]
CRUMBS = []
for _ in range(46):
    t0 = rng.uniform(17.75, 18.85)
    CRUMBS.append(dict(t0=t0, dx=rng.uniform(-0.05, 0.35) * CH_R, dy=rng.uniform(-0.25, 0.25) * CH_R,
                       vx=rng.uniform(-80, 420), vy=rng.uniform(-620, -180),
                       r=rng.uniform(5, 12), c=rng.choice(CRUMB_COLORS), life=rng.uniform(0.5, 0.8)))


def chomper_sprite(mouth_deg):
    pad = 30
    size = 2 * (CH_R + pad)
    im = Image.new("RGBA", (s(size), s(size)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = CH_R + pad
    bbox = (s(c - CH_R), s(c - CH_R), s(c + CH_R), s(c + CH_R))
    start, end = mouth_deg, 360 - mouth_deg
    d.pieslice(bbox, start, end, fill=MUSTARD + (255,))
    # soft shading: darker lower rim
    shade = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    sd.ellipse((s(c - CH_R * 0.95), s(c - CH_R * 0.55), s(c + CH_R * 1.25), s(c + CH_R * 1.6)),
               fill=(200, 120, 20, 90))
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).pieslice(bbox, start, end, fill=255)
    shade.putalpha(Image.composite(shade.getchannel("A"), Image.new("L", im.size, 0), mask))
    im.alpha_composite(shade)
    # highlight
    hl = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse((s(c - CH_R * 0.62), s(c - CH_R * 0.78), s(c - CH_R * 0.22), s(c - CH_R * 0.5)),
                               fill=(255, 255, 255, 60))
    im.alpha_composite(hl.filter(ImageFilter.GaussianBlur(s(14))))
    # eye with a glint
    ex, ey, er = c + CH_R * 0.12, c - CH_R * 0.52, CH_R * 0.11
    d.ellipse((s(ex - er), s(ey - er), s(ex + er), s(ey + er)), fill=(40, 16, 20, 255))
    gr = er * 0.38
    d.ellipse((s(ex - er * 0.35 - gr), s(ey - er * 0.35 - gr), s(ex - er * 0.35 + gr), s(ey - er * 0.35 + gr)),
              fill=(255, 255, 255, 255))
    im = im.resize((size, size), Image.LANCZOS)
    # drop shadow
    sh = Image.new("RGBA", im.size, (20, 0, 10, 0))
    sh.putalpha(im.getchannel("A").point(lambda v: v * 0.45).filter(ImageFilter.GaussianBlur(10)))
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.alpha_composite(sh, (0, 8))
    out.alpha_composite(im)
    return out, c


SPRITES = {}


def render_chomper(t, out, clean):
    if not (CH_T_START <= t <= CH_T_END + 0.1):
        return
    cx, cy = chomper_pos(t)
    # everything the chomper has passed is eaten: show the clean plate there
    rx = int(min(max(cx, 0), W))
    if rx > 0:
        # feathered right edge so the cut through the burger's shadow is invisible
        h = REVEAL_Y[1] - REVEAL_Y[0]
        ramp = Image.linear_gradient("L").rotate(-90, expand=True).resize((FEATHER, h))  # 255 -> 0 left to right
        mask = Image.new("L", (rx, h), 255)
        mask.paste(ramp.crop((max(0, FEATHER - rx), 0, FEATHER, h)), (max(0, rx - FEATHER), 0))
        patch = clean.crop((0, REVEAL_Y[0], rx, REVEAL_Y[1]))
        patch.putalpha(mask)
        out.alpha_composite(patch, (0, REVEAL_Y[0]))
    # crumbs
    cd = ImageDraw.Draw(out)
    for p in CRUMBS:
        dt = t - p["t0"]
        if 0 <= dt <= p["life"]:
            x0, y0 = chomper_pos(p["t0"])
            x = x0 + CH_R * 0.55 + p["dx"] + p["vx"] * dt
            y = y0 + p["dy"] + p["vy"] * dt + 0.5 * 1800 * dt * dt
            a = int(255 * (1 - dt / p["life"]) ** 0.5)
            r = p["r"]
            cd.ellipse((x - r, y - r, x + r, y + r), fill=p["c"] + (a,))
    # body
    phase = abs(math.sin(math.pi * CH_MOUTH_HZ * (t - CH_T_START)))
    mouth = round(4 + 38 * phase)
    if mouth not in SPRITES:
        SPRITES[mouth] = chomper_sprite(mouth)
    spr, c = SPRITES[mouth]
    _paste_clipped(out, spr, int(cx - c), int(cy - c))


def _paste_clipped(dst, src, x, y):
    sx, sy = max(0, -x), max(0, -y)
    dx, dy = max(0, x), max(0, y)
    w = min(src.width - sx, dst.width - dx)
    h = min(src.height - sy, dst.height - dy)
    if w > 0 and h > 0:
        dst.alpha_composite(src.crop((sx, sy, sx + w, sy + h)), (dx, dy))


# --- pack finale ---------------------------------------------------------------

PACK = os.path.join(HERE, "assets", "pack.png")
PACK_T0 = 19.1            # the burger is cut out of the shot at 19.05 s
TAIL = 3.2                # hold the empty last frame this long so the finale can play
PACK_W, PACK_C = 600, (540, 800)
CTA = "Попробуйте!"
CTA_SIZE, CTA_Y = 104, 1290

_pack_img = None
cta_font = font(CTA_SIZE, b"Black")


def pack_img():
    global _pack_img
    if _pack_img is None:
        _pack_img = Image.open(PACK).convert("RGBA")
    return _pack_img


def ease_back(t, k=1.9):
    t = min(max(t, 0.0), 1.0) - 1
    return 1 + t * t * ((k + 1) * t + k)


def elastic(t):
    t = min(max(t, 0.0), 1.0)
    if t in (0.0, 1.0):
        return t
    return 2 ** (-9 * t) * math.sin((t - 0.08) * 2 * math.pi / 0.32) + 1


def sparkle(d, x, y, r, al, color):
    # four-point twinkle
    w = r * 0.22
    d.polygon([(x, y - r), (x + w, y - w), (x + r, y), (x + w, y + w),
               (x, y + r), (x - w, y + w), (x - r, y), (x - w, y - w)], fill=color + (al,))


SPARKS = [(-330, -250, 0.0), (320, -330, 0.35), (350, 120, 0.7), (-345, 210, 1.05),
          (-250, -430, 1.4), (270, 360, 0.2), (40, -470, 0.9)]


def render_pack(t, out):
    tt = t - PACK_T0
    if tt < 0:
        return
    pk = pack_img()
    # fly up from below with overshoot, spin settles elastically, then float + wiggle
    rise = ease_back(tt / 0.75)
    y_off = (1 - rise) * 1100
    rot = -28 * (1 - elastic(tt / 1.1))
    scale = 0.55 + 0.45 * ease_back(tt / 0.6, 2.4)
    if tt > 0.75:
        f = tt - 0.75
        y_off += 16 * math.sin(2 * math.pi * 0.7 * f)
        rot += 2.5 * math.sin(2 * math.pi * 0.5 * f)
        scale *= 1 + 0.015 * math.sin(2 * math.pi * 1.4 * f)
    for tw in (1.7, 3.4):  # "look at me" wiggle
        if tw <= tt <= tw + 0.6:
            k = (tt - tw) / 0.6
            rot += 7 * math.sin(k * 4 * math.pi) * (1 - k)
            scale *= 1 + 0.07 * math.sin(k * math.pi)

    w = PACK_W * scale
    img = pk.resize((int(w), int(w * pk.height / pk.width)), Image.BICUBIC)

    # glossy shine sweeping across the box
    for ts in (0.9, 2.6):
        k = (tt - ts) / 0.55
        if 0 <= k <= 1:
            band = Image.new("L", (img.width * 3, img.height * 3), 0)
            bx = band.width * (0.2 + 0.6 * k)
            ImageDraw.Draw(band).rectangle((bx - img.width * 0.12, 0, bx + img.width * 0.12, band.height), fill=150)
            band = band.filter(ImageFilter.GaussianBlur(img.width * 0.05)).rotate(25)
            band = band.crop((img.width, img.height, img.width * 2, img.height * 2))
            shine = Image.new("RGBA", img.size, WHITE + (0,))
            shine.putalpha(ImageChops.multiply(band, img.getchannel("A")))
            img = img.copy()
            img.alpha_composite(shine)

    img = img.rotate(rot, resample=Image.BICUBIC, expand=True)
    cx, cy = PACK_C[0], PACK_C[1] + y_off

    # soft contact shadow on the floor, smaller when the box floats higher
    if tt > 0.2:
        sa = min(1, (tt - 0.2) / 0.4)
        lift = max(0.0, y_off) / 200
        sw = w * (0.85 - 0.1 * min(lift, 1))
        sh = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse((540 - sw / 2, 120, 540 + sw / 2, 170), fill=(10, 0, 8, int(150 * sa)))
        out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)), (0, int(PACK_C[1] + w * 0.56 - 145)))

    drop = Image.new("RGBA", img.size, (15, 0, 10, 0))
    drop.putalpha(img.getchannel("A").point(lambda v: v * 0.5).filter(ImageFilter.GaussianBlur(16)))
    _paste_clipped(out, drop, int(cx - img.width / 2 + 10), int(cy - img.height / 2 + 22))
    _paste_clipped(out, img, int(cx - img.width / 2), int(cy - img.height / 2))

    # twinkles around the box once it has landed
    if tt > 0.7:
        d = ImageDraw.Draw(out)
        for dx, dy, ph in SPARKS:
            k = ((tt - 0.7 + ph) % 1.4) / 1.4
            a = math.sin(k * math.pi)
            if a > 0.05:
                sparkle(d, cx + dx, cy + dy, 10 + 16 * a, int(255 * a), MUSTARD if ph % 0.7 < 0.35 else WHITE)

    # "Попробуйте!" letters pop in one by one, then ride a little wave
    letters = list(CTA)
    total = cta_font.getlength(CTA) / SS
    x0 = W / 2 - total / 2
    for n, ch in enumerate(letters):
        lt = tt - 0.55 - n * 0.055
        if lt <= 0 or ch == " ":
            continue
        sc = ease_back(lt / 0.35, 3.0)
        lx = x0 + cta_font.getlength(CTA[:n]) / SS
        lw = cta_font.getlength(ch) / SS
        ly = CTA_Y - 14 * math.sin(2 * math.pi * 0.9 * lt - n * 0.55) * min(1, lt / 0.5)
        size = int(CTA_SIZE * 1.6)
        g = Image.new("RGBA", (s(size), s(size)), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        gd.text((s(size / 2) + s(4), s(size / 2) + s(6)), ch, font=cta_font, fill=THEME["cta_shadow"] + (200,), anchor="mm")
        gd.text((s(size / 2), s(size / 2)), ch, font=cta_font, fill=THEME["cta"] + (255,), anchor="mm")
        k = max(1, int(size * sc))
        g = g.resize((k, k), Image.LANCZOS)
        _paste_clipped(out, g, int(lx + lw / 2 - k / 2), int(ly - k / 2))


def render(t, clean, finale="chomper"):
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    render_card(t, out)
    if finale == "chomper":
        render_chomper(t, out, clean)
    else:
        render_pack(t, out)
    return out


# --- ffmpeg ------------------------------------------------------------------

def duration(path):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]))


def grab_frame(src, t):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(t), "-i", src, "-frames:v", "1",
                                   "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


# per-run state, set up before the worker pool forks
CTX = {}


def setup(src, finale, theme):
    global THEME
    THEME = THEMES[theme]
    clean = grab_frame(src, CLEAN_PLATE_T)
    rc = Recolor(clean, *THEME["backdrop"]) if THEME["backdrop"] else None
    if rc:
        clean = rc(clean)
    CTX.update(finale=finale, recolor=rc, clean=Image.fromarray(clean).convert("RGBA"))


def process_frame(job):
    i, raw = job
    t = i / FPS
    arr = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
    if CTX["recolor"]:
        arr = CTX["recolor"](arr)
    frame = Image.fromarray(arr).convert("RGBA")
    a = card_alpha(t)
    if a > 0:  # frosted glass: blur what is behind the card
        box = (CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + CARD_H)
        bl = frame.crop(box).filter(ImageFilter.GaussianBlur(BLUR))
        bl.putalpha(GLASS_MASK.point(lambda v: int(v * a)))
        frame.alpha_composite(bl, box[:2])
    frame.alpha_composite(render(t, CTX["clean"], CTX["finale"]))
    return frame.convert("RGB").tobytes()


def main(src, dst, finale, theme):
    tail = TAIL if finale == "pack" else 0
    src_len = duration(src) - (0.1 if tail else 0)   # source ends on two dark fade frames
    total = src_len + tail
    setup(src, finale, theme)
    dec = subprocess.Popen([
        "ffmpeg", "-v", "error", "-i", src, "-an", "-vf",
        f"trim=end={src_len:.3f},setpts=PTS-STARTPTS,scale={W}:{H},fps={FPS},"
        f"tpad=stop_mode=clone:stop_duration={tail}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", src, "-filter_complex", "[1:a:0]apad[a]", "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst,
    ], stdin=subprocess.PIPE)

    def frames():
        i, size = 0, W * H * 3
        while True:
            raw = dec.stdout.read(size)
            if len(raw) < size:
                return
            yield i, raw
            i += 1

    with Pool(os.cpu_count()) as pool:
        for out in pool.imap(process_frame, frames(), chunksize=2):
            enc.stdin.write(out)
    enc.stdin.close()
    dec.wait()
    sys.exit(enc.wait())


if __name__ == "__main__":
    args = sys.argv[1:]
    opts = {"--finale": "chomper", "--theme": "red"}
    for k in opts:
        if k in args:
            j = args.index(k)
            opts[k] = args[j + 1]
            del args[j:j + 2]
    finale, theme = opts["--finale"], opts["--theme"]
    if len(args) == 2:
        main(args[0], args[1], finale, theme)
    elif len(args) == 3 and args[0] == "--preview":
        # --preview INPUT T : write preview_T.jpg for that moment
        src, t = args[1], float(args[2])
        setup(src, finale, theme)
        raw = grab_frame(src, min(t, duration(src) - 0.15)).tobytes()
        Image.frombytes("RGB", (W, H), process_frame((round(t * FPS), raw))).save(f"preview_{t:05.2f}.jpg")
    else:
        sys.exit(__doc__)
