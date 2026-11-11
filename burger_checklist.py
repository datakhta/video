#!/usr/bin/env python3
"""Animated burger checklist + FISH&MORE logo overlay for a vertical video.

Each item gets ticked the moment that ingredient lands on the burger.
Usage: python3 burger_checklist.py INPUT.mov OUTPUT.mp4   
"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
SS = 2
FPS = 30

TITLE = "Бургер Эби Катцу"
# (text, check time in seconds) — times found frame by frame in the source
ITEMS = [
    ("булка", 0.30),
    ("листья салата", 0.90),
    ("лук", 1.80),
    ("авокадо", 2.40),
    ("котлета эби катцу от FISH&MORE", 2.90),
    ("огурец", 3.30),
    ("помидор", 4.50),
    ("соус", 5.00),
    ("булка", 5.40),
    ("наслаждаемся!", 6.20),
]
CARD_IN = (0.0, 0.3)       # start, duration
CARD_OUT = (16.4, 0.5)     # burger drives up into the card area after ~17 s

FONT = os.path.join(HERE, "fonts", "Comfortaa.ttf")
LOGO = os.path.join(HERE, "assets", "fishmore_logo.png")

WHITE = (255, 255, 255)
WINE = (110, 8, 30)        # tick colour, picked from the red wall
BLUR = 22                  # frosted-glass blur radius

# layout (1x px)
CARD_X, CARD_Y, CARD_W = 40, 56, W - 80
PAD = 34
TITLE_SIZE, TEXT_SIZE = 46, 30
BOX, GAP, LINE_H, ROW_GAP, COL_GAP = 36, 14, 40, 14, 24
ROWS = 5
LOGO_W, LOGO_MARGIN = 200, 48


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


title_font = font(TITLE_SIZE, b"Bold")
text_font = font(TEXT_SIZE, b"Bold")

col_w = (CARD_W - 2 * PAD - COL_GAP) / 2
text_w = col_w - BOX - GAP

# two columns, rows aligned across columns
wrapped = [wrap(txt, text_font, s(text_w)) for txt, _ in ITEMS]
layout = [None] * len(ITEMS)
y = CARD_Y + PAD + TITLE_SIZE + 26
for r in range(ROWS):
    idx = [i for i in (r, r + ROWS) if i < len(ITEMS)]
    for c, i in enumerate(idx):
        layout[i] = (CARD_X + PAD + c * (col_w + COL_GAP), y)
    y += max(len(wrapped[i]) for i in idx) * LINE_H + ROW_GAP
CARD_H = y - ROW_GAP + PAD - CARD_Y

# logo knocked out to white (no plate), with a faint shadow to lift it off the floor
logo = Image.open(LOGO)
logo = logo.resize((LOGO_W, round(logo.height * LOGO_W / logo.width)), Image.LANCZOS)
la = logo.getchannel("A").point(lambda v: int(v * 0.92))
sp = 8
pill = Image.new("RGBA", (logo.width + 2 * sp, logo.height + 2 * sp), (0, 0, 0, 0))
shadow = Image.new("L", pill.size, 0)
shadow.paste(la.point(lambda v: int(v * 0.5)), (sp, sp + 1))
pill.paste(Image.new("RGBA", pill.size, (0, 0, 0, 255)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(3)))
white = Image.new("RGBA", logo.size, WHITE + (0,))
white.putalpha(la)
pill.alpha_composite(white, (sp, sp))
PILL_POS = (W - LOGO_MARGIN - logo.width - sp, H - LOGO_MARGIN - 40 - logo.height - sp)

# only the strips that change are rendered and piped to ffmpeg
TOP_H = CARD_Y + CARD_H + 50


def draw_check(d, cx, cy, k, al):
    pts = [(cx - 9, cy + 1), (cx - 2, cy + 8), (cx + 10, cy - 8)]
    l1 = ((pts[1][0] - pts[0][0]) ** 2 + (pts[1][1] - pts[0][1]) ** 2) ** 0.5
    l2 = ((pts[2][0] - pts[1][0]) ** 2 + (pts[2][1] - pts[1][1]) ** 2) ** 0.5
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
        d.ellipse((s(x - 2.5), s(y - 2.5), s(x + 2.5), s(y + 2.5)), fill=WHITE + (al,))


def card_alpha(t):
    # linear, so it matches ffmpeg's fade on the blurred glass layer
    a_in = min(max((t - CARD_IN[0]) / CARD_IN[1], 0), 1)
    a_out = min(max((t - CARD_OUT[0]) / CARD_OUT[1], 0), 1)
    return a_in * (1 - a_out)


# static rounded mask for the blurred-background "glass"
GLASS_MASK = Image.new("L", (s(CARD_W), s(CARD_H)), 0)
ImageDraw.Draw(GLASS_MASK).rounded_rectangle((0, 0, s(CARD_W) - 1, s(CARD_H) - 1), s(34), fill=255)
GLASS_MASK = GLASS_MASK.resize((CARD_W, CARD_H), Image.LANCZOS)


def render_card(t):
    a = card_alpha(t)
    out = Image.new("RGBA", (W, TOP_H), (0, 0, 0, 0))
    if a <= 0:
        return out
    al = int(255 * a)

    # glass: faint white tint + light rim + soft top highlight
    glass = Image.new("RGBA", (s(W), s(TOP_H)), (0, 0, 0, 0))
    g = ImageDraw.Draw(glass)
    rect = (s(CARD_X), s(CARD_Y), s(CARD_X + CARD_W), s(CARD_Y + CARD_H))
    g.rounded_rectangle(rect, s(34), fill=WHITE + (int(34 * a),),
                        outline=WHITE + (int(110 * a),), width=s(2))

    # content on its own layer so it gets a soft shadow for legibility
    ink = Image.new("RGBA", (s(W), s(TOP_H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(ink)
    d.text((s(CARD_X + PAD), s(CARD_Y + PAD)), TITLE, font=title_font, fill=WHITE + (al,), anchor="lt")
    for (txt, t_chk), lines, (x, y) in zip(ITEMS, wrapped, layout):
        fill = prog(t, t_chk, 0.18)
        check = prog(t, t_chk + 0.08, 0.25)
        pop = 1 + 0.2 * max(0.0, 1 - abs((t - t_chk - 0.12) / 0.12)) if t >= t_chk else 1
        cx, cy = x + BOX / 2, y + LINE_H / 2
        h = BOX / 2 * pop
        box = (s(cx - h), s(cy - h), s(cx + h), s(cy + h))
        d.rounded_rectangle(box, s(10), outline=WHITE + (al,), width=s(3))
        if fill > 0:
            d.rounded_rectangle(box, s(10), fill=WHITE + (int(al * fill),), outline=WHITE + (al,), width=s(3))
        if check > 0:
            draw_check(d, cx, cy, check, al)
        for k, ln in enumerate(lines):
            d.text((s(x + BOX + GAP), s(y + k * LINE_H + LINE_H / 2)), ln, font=text_font,
                   fill=WHITE + (al,), anchor="lm")

    glass = glass.resize((W, TOP_H), Image.LANCZOS)
    ink = ink.resize((W, TOP_H), Image.LANCZOS)
    sh = Image.new("RGBA", ink.size, (40, 0, 10, 0))
    sh.putalpha(ink.getchannel("A").point(lambda v: v * 0.55).filter(ImageFilter.GaussianBlur(4)))
    out.alpha_composite(glass)
    out.alpha_composite(sh, (0, 2))
    out.alpha_composite(ink)
    return out


def logo_frame(t):
    a = prog(t, 0.0, 0.4)
    p = pill.copy()
    p.putalpha(p.getchannel("A").point(lambda v: int(v * a)))
    return p


def duration(path):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]))


def main(src, dst):
    n = int(duration(src) * FPS) + 2
    # card strip comes in on stdin; the logo is a static PNG faded in by ffmpeg
    logo_png = os.path.join(HERE, "assets", "_logo_pill.png")
    mask_png = os.path.join(HERE, "assets", "_glass_mask.png")
    pill.save(logo_png)
    GLASS_MASK.save(mask_png)
    fi, di = CARD_IN
    fo, do = CARD_OUT
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-i", src,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{TOP_H}", "-r", str(FPS), "-i", "-",
        "-loop", "1", "-i", logo_png,
        "-loop", "1", "-i", mask_png,
        "-filter_complex",
        f"[0:v]scale={W}:{H},fps={FPS},split[bg][src];"
        # frosted glass: blur the wall behind the card, clip to rounded rect, fade with the card
        f"[src]crop={CARD_W}:{CARD_H}:{CARD_X}:{CARD_Y},gblur=sigma={BLUR},eq=brightness=0.03,format=rgba[bl];"
        f"[3:v]format=gray[m];[bl][m]alphamerge,"
        f"fade=in:st={fi}:d={di}:alpha=1,fade=out:st={fo}:d={do}:alpha=1[glass];"
        f"[bg][glass]overlay={CARD_X}:{CARD_Y}:shortest=1[g];"
        f"[g][1:v]overlay=0:0:shortest=1[c];"
        f"[2:v]format=rgba,fade=in:st=0:d=0.4:alpha=1[l];"
        f"[c][l]overlay={PILL_POS[0]}:{PILL_POS[1]}:shortest=1,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "slow", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst,
    ], stdin=subprocess.PIPE)
    for i in range(n):
        ff.stdin.write(render_card(i / FPS).tobytes())
    ff.stdin.close()
    rc = ff.wait()
    os.remove(logo_png)
    os.remove(mask_png)
    sys.exit(rc)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
