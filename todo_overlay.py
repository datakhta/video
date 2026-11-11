#!/usr/bin/env python3
"""Render an animated to-do list overlay and burn it into a vertical video.

Usage: python3 todo_overlay.py INPUT.mov OUTPUT.mp4
"""
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W = 1080            # output video width (portrait)
SS = 2              # supersampling factor for smooth edges
FPS = 30

TITLE = "TODO"
ITEMS = [
    # text, appear time (s), check time (s)
    ("Дождаться мужчину с командировки", 0.9, 3.6),
    ("Отправить его в отпуск на два месяца", 5.0, 8.4),
    ("Наслаждаться горячими завтраками каждый день, пока сама работаешь", 10.0, 15.5),
]

FONT_BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FONT_TEXT = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"

INK = (38, 32, 30)
ACCENT = (235, 120, 60)
CARD = (255, 252, 247)

# layout (in 1x pixels)
CARD_X, CARD_Y, CARD_W = 54, 110, W - 108
PAD = 44
BOX = 50
GAP = 26                 # between checkbox and text
TITLE_SIZE, TEXT_SIZE = 62, 42
LINE_H = 54
ITEM_GAP = 30


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def prog(t, start, dur):
    return ease_out((t - start) / dur)


def wrap(text, font, width):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if font.getlength(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def s(v):
    return int(round(v * SS))


title_font = ImageFont.truetype(FONT_BOLD, s(TITLE_SIZE))
text_font = ImageFont.truetype(FONT_TEXT, s(TEXT_SIZE))
text_w = CARD_W - 2 * PAD - BOX - GAP

# precompute layout
layout = []
y = CARD_Y + PAD + TITLE_SIZE + 34
for text, t_in, t_chk in ITEMS:
    lines = wrap(text, text_font, s(text_w))
    layout.append((lines, y, t_in, t_chk))
    y += len(lines) * LINE_H + ITEM_GAP
CARD_H = y - ITEM_GAP + PAD - CARD_Y
H = CARD_Y + CARD_H + 60  # overlay strip height

# static shadow
shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle(
    (CARD_X, CARD_Y + 10, CARD_X + CARD_W, CARD_Y + CARD_H + 10), 38, fill=(0, 0, 0, 90))
shadow = shadow.filter(ImageFilter.GaussianBlur(18))


def render(t):
    a_card = prog(t, 0.15, 0.6)
    if a_card <= 0:
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dy = (1 - a_card) * -40

    big = Image.new("RGBA", (s(W), s(H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle(
        (s(CARD_X), s(CARD_Y + dy), s(CARD_X + CARD_W), s(CARD_Y + CARD_H + dy)),
        s(38), fill=CARD + (int(232 * a_card),))

    # title + accent underline
    tx, ty = CARD_X + PAD, CARD_Y + PAD + dy
    d.text((s(tx), s(ty)), TITLE, font=title_font, fill=INK + (int(255 * a_card),), anchor="lt")
    ul = prog(t, 0.5, 0.6)
    d.rounded_rectangle((s(tx), s(ty + TITLE_SIZE + 8), s(tx + 150 * ul + 1), s(ty + TITLE_SIZE + 16)),
                        s(4), fill=ACCENT + (int(255 * a_card),))

    for lines, iy, t_in, t_chk in layout:
        a = prog(t, t_in, 0.45)
        if a <= 0:
            continue
        ox = (1 - a) * 40
        iy += dy
        bx, by = CARD_X + PAD + ox, iy + (LINE_H - BOX) / 2
        fill = prog(t, t_chk, 0.22)
        check = prog(t, t_chk + 0.12, 0.3)
        strike = prog(t, t_chk + 0.3, 0.6)
        al = int(255 * a)

        # checkbox (with a little pop when checked)
        pop = 1 + 0.18 * max(0.0, 1 - abs((t - t_chk - 0.15) / 0.15)) if t >= t_chk else 1
        c = BOX / 2
        half = c * pop
        cx, cy = bx + c, by + c
        box = (s(cx - half), s(cy - half), s(cx + half), s(cy + half))
        d.rounded_rectangle(box, s(13), outline=INK + (al,), width=s(4))
        if fill > 0:
            d.rounded_rectangle(box, s(13), fill=ACCENT + (int(al * fill),),
                                outline=ACCENT + (int(al * fill),), width=s(4))
        if check > 0:
            pts = [(cx - 12, cy + 1), (cx - 3, cy + 10), (cx + 14, cy - 10)]
            seg1 = ((pts[1][0] - pts[0][0]) ** 2 + (pts[1][1] - pts[0][1]) ** 2) ** 0.5
            seg2 = ((pts[2][0] - pts[1][0]) ** 2 + (pts[2][1] - pts[1][1]) ** 2) ** 0.5
            L = (seg1 + seg2) * check
            path = [pts[0]]
            if L <= seg1:
                f = L / seg1
                path.append((pts[0][0] + (pts[1][0] - pts[0][0]) * f, pts[0][1] + (pts[1][1] - pts[0][1]) * f))
            else:
                f = (L - seg1) / seg2
                path += [pts[1], (pts[1][0] + (pts[2][0] - pts[1][0]) * f, pts[1][1] + (pts[2][1] - pts[1][1]) * f)]
            d.line([(s(x), s(y)) for x, y in path], fill=(255, 255, 255, al), width=s(6), joint="curve")
            for x, y in (path[0], path[-1]):
                r = 3
                d.ellipse((s(x - r), s(y - r), s(x + r), s(y + r)), fill=(255, 255, 255, al))

        # text (dims once done)
        txa = int(al * (1 - 0.45 * strike))
        lx = bx + BOX + GAP
        widths = [text_font.getlength(ln) / SS for ln in lines]
        total = sum(widths)
        done = total * strike
        for k, ln in enumerate(lines):
            ly = iy + k * LINE_H + LINE_H / 2
            d.text((s(lx), s(ly)), ln, font=text_font, fill=INK + (txa,), anchor="lm")
            seg = min(max(done, 0), widths[k])
            done -= widths[k]
            if seg > 0:
                d.rounded_rectangle((s(lx - 4), s(ly - 2), s(lx + seg + 4), s(ly + 3)),
                                    s(2), fill=ACCENT + (al,))

    frame = big.resize((W, H), Image.LANCZOS)
    sh = shadow.copy()
    sh.putalpha(sh.getchannel("A").point(lambda v: int(v * a_card)))
    if dy:
        sh = sh.transform(sh.size, Image.AFFINE, (1, 0, 0, 0, 1, -dy))
    return Image.alpha_composite(sh, frame)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path])
    return float(out)


def main(src, dst):
    n = int(duration(src) * FPS) + 2
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-i", src,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-filter_complex", f"[0:v]scale={W}:-2,fps={FPS}[bg];[bg][1:v]overlay=0:0:shortest=1,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst,
    ], stdin=subprocess.PIPE)
    for i in range(n):
        ff.stdin.write(render(i / FPS).tobytes())
    ff.stdin.close()
    sys.exit(ff.wait())


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:  # preview stills
        for t in (0.4, 2.0, 4.2, 9.5, 16.5):
            render(t).save(f"preview_{t:04.1f}.png")
