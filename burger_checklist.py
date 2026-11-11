#!/usr/bin/env python3
"""Animated burger checklist + chomper finale for a vertical video.

Each item gets ticked the moment that ingredient lands on the burger; at the
end a round chomper flies in and eats the burger.
Usage: python3 burger_checklist.py INPUT.mov OUTPUT.mp4
"""
import math
import os
import random
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
WINE = (110, 8, 30)        # tick colour, picked from the red wall
MUSTARD = (255, 204, 64)   # title + chomper, like the burger sauce
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
OV_H = 960                                      # overlay strip height (card + chomper)


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
    d.line([(s(x), s(y)) for x, y in path], fill=WINE + (al,), width=s(5), joint="curve")
    for x, y in (path[0], path[-1]):
        d.ellipse((s(x - 2.5), s(y - 2.5), s(x + 2.5), s(y + 2.5)), fill=WINE + (al,))


def card_alpha(t):
    # linear, so it matches ffmpeg's fade on the blurred glass layer
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

    # glass: just a faint white tint, no rim (the blur itself comes from ffmpeg)
    glass = Image.new("RGBA", (W, TOP_H), (0, 0, 0, 0))
    tint = Image.new("RGBA", (CARD_W, CARD_H), WHITE + (0,))
    tint.putalpha(GLASS_MASK.point(lambda v: int(v * 22 / 255 * a)))
    glass.alpha_composite(tint, (CARD_X, CARD_Y))

    # content on its own layer so it gets a soft shadow for legibility
    ink = Image.new("RGBA", (s(W), s(TOP_H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(ink)
    d.text((s(CARD_X + PAD), s(CARD_Y + PAD)), TITLE, font=title_font, fill=MUSTARD + (al,), anchor="lt")
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
    sh = Image.new("RGBA", ink.size, (40, 0, 10, 0))
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


def render(t, clean):
    out = Image.new("RGBA", (W, OV_H), (0, 0, 0, 0))
    render_card(t, out)
    render_chomper(t, out, clean)
    return out


# --- ffmpeg ------------------------------------------------------------------

def duration(path):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]))


def grab_frame(src, t):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(t), "-i", src, "-frames:v", "1",
                                   "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
    return Image.frombytes("RGBA", (W, H), raw)


def main(src, dst):
    n = int(duration(src) * FPS) + 2
    clean = grab_frame(src, CLEAN_PLATE_T)
    mask_png = os.path.join(HERE, "assets", "_glass_mask.png")
    GLASS_MASK.save(mask_png)
    fi, di = CARD_IN
    fo, do = CARD_OUT
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-i", src,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{OV_H}", "-r", str(FPS), "-i", "-",
        "-loop", "1", "-i", mask_png,
        "-filter_complex",
        f"[0:v]scale={W}:{H},fps={FPS},split[bg][src];"
        # frosted glass: blur the wall behind the card, clip to rounded rect, fade with the card
        f"[src]crop={CARD_W}:{CARD_H}:{CARD_X}:{CARD_Y},gblur=sigma={BLUR},format=rgba[bl];"
        f"[2:v]format=gray[m];[bl][m]alphamerge,"
        f"fade=in:st={fi}:d={di}:alpha=1,fade=out:st={fo}:d={do}:alpha=1[glass];"
        f"[bg][glass]overlay={CARD_X}:{CARD_Y}:shortest=1[g];"
        f"[g][1:v]overlay=0:0:shortest=1,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "slow", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst,
    ], stdin=subprocess.PIPE)
    for i in range(n):
        ff.stdin.write(render(i / FPS, clean).tobytes())
    ff.stdin.close()
    rc = ff.wait()
    os.remove(mask_png)
    sys.exit(rc)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "--preview":
        # --preview INPUT T : write preview_T.png composited on that source frame
        src, t = sys.argv[2], float(sys.argv[3])
        frame = grab_frame(src, t)
        frame.alpha_composite(render(t, grab_frame(src, CLEAN_PLATE_T)))
        frame.convert("RGB").save(f"preview_{t:05.2f}.jpg")
    else:
        sys.exit(__doc__)
