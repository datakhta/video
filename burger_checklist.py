#!/usr/bin/env python3
"""Animated burger checklist + FISH&MORE logo overlay for a vertical video.

Each item gets ticked the moment that ingredient lands on the burger.
Usage: python3 burger_checklist.py INPUT.mov OUTPUT.mp4   (no args -> preview PNGs)
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

NAVY = (14, 58, 93)        # logo dark blue
SKY = (141, 198, 232)      # logo light blue
WHITE = (255, 255, 255)
BOX_BG = tuple((c + 255) // 2 for c in SKY)  # unchecked box: pale blue

# layout (1x px)
CARD_X, CARD_Y, CARD_W = 40, 56, W - 80
PAD = 34
TITLE_SIZE, TEXT_SIZE = 46, 30
BOX, GAP, LINE_H, ROW_GAP, COL_GAP = 36, 14, 40, 14, 24
ROWS = 5
LOGO_W, LOGO_MARGIN = 300, 44


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

shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle(
    (CARD_X, CARD_Y + 10, CARD_X + CARD_W, CARD_Y + CARD_H + 10), 34, fill=(0, 0, 0, 110))
shadow = shadow.filter(ImageFilter.GaussianBlur(18))

# logo on a white pill so the navy "FISH&" reads on the dark background
logo = Image.open(LOGO)
logo = logo.resize((LOGO_W, round(logo.height * LOGO_W / logo.width)), Image.LANCZOS)
lp_x, lp_y = 26, 18
pill = Image.new("RGBA", (LOGO_W + 2 * lp_x, logo.height + 2 * lp_y), (0, 0, 0, 0))
ImageDraw.Draw(pill).rounded_rectangle((0, 0, pill.width - 1, pill.height - 1),
                                       pill.height // 2, fill=WHITE + (240,))
pill.alpha_composite(logo, (lp_x, lp_y))
PILL_POS = (W - LOGO_MARGIN - pill.width, H - LOGO_MARGIN - 40 - pill.height)

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
    d.line([(s(x), s(y)) for x, y in path], fill=WHITE + (al,), width=s(5), joint="curve")
    for x, y in (path[0], path[-1]):
        d.ellipse((s(x - 2.5), s(y - 2.5), s(x + 2.5), s(y + 2.5)), fill=WHITE + (al,))


def render_card(t):
    a = prog(t, *CARD_IN) * (1 - prog(t, *CARD_OUT))
    out = Image.new("RGBA", (W, TOP_H), (0, 0, 0, 0))
    if a <= 0:
        return out
    dy = (1 - prog(t, *CARD_IN)) * -30 + prog(t, *CARD_OUT) * -30
    big = Image.new("RGBA", (s(W), s(TOP_H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((s(CARD_X), s(CARD_Y + dy), s(CARD_X + CARD_W), s(CARD_Y + CARD_H + dy)),
                        s(34), fill=SKY + (int(240 * a),))
    al = int(255 * a)
    d.text((s(CARD_X + PAD), s(CARD_Y + PAD + dy)), TITLE, font=title_font, fill=NAVY + (al,), anchor="lt")

    for (txt, t_chk), lines, (x, y) in zip(ITEMS, wrapped, layout):
        y += dy
        fill = prog(t, t_chk, 0.18)
        check = prog(t, t_chk + 0.08, 0.25)
        pop = 1 + 0.2 * max(0.0, 1 - abs((t - t_chk - 0.12) / 0.12)) if t >= t_chk else 1
        cx, cy = x + BOX / 2, y + LINE_H / 2
        h = BOX / 2 * pop
        box = (s(cx - h), s(cy - h), s(cx + h), s(cy + h))
        d.rounded_rectangle(box, s(10), fill=BOX_BG + (int(240 * a),), outline=NAVY + (al,), width=s(3))
        if fill > 0:
            d.rounded_rectangle(box, s(10), fill=NAVY + (int(al * fill),), outline=NAVY + (al,), width=s(3))
        if check > 0:
            draw_check(d, cx, cy, check, al)
        for k, ln in enumerate(lines):
            d.text((s(x + BOX + GAP), s(y + k * LINE_H + LINE_H / 2)), ln, font=text_font,
                   fill=NAVY + (al,), anchor="lm")

    big = big.resize((W, TOP_H), Image.LANCZOS)
    sh = shadow.crop((0, 0, W, TOP_H))
    sh.putalpha(sh.getchannel("A").point(lambda v: int(v * a)))
    if dy:
        sh = sh.transform(sh.size, Image.AFFINE, (1, 0, 0, 0, 1, -dy))
    out.alpha_composite(sh)
    out.alpha_composite(big)
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
    pill.save(logo_png)
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-i", src,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{TOP_H}", "-r", str(FPS), "-i", "-",
        "-loop", "1", "-i", logo_png,
        "-filter_complex",
        f"[0:v]scale={W}:{H},fps={FPS}[bg];[bg][1:v]overlay=0:0:shortest=1[c];"
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
    sys.exit(rc)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        for t in (3.1, 7.0):
            f = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            f.alpha_composite(render_card(t))
            f.alpha_composite(logo_frame(t), PILL_POS)
            f.save(f"preview_{t:04.1f}.png")
