"""Swap the backdrop colours of a static-camera shot, keeping the subject untouched.

Uses a clean plate (a frame of the empty set) to tell backdrop from subject:
a pixel is backdrop when its chromaticity matches the clean plate at that spot
and it isn't much brighter than it, so shadows and reflections on the floor are
recoloured too. New colours keep the original lighting (pixel / plate luminance)
and the original wall-to-floor transition, softened a little more since the new
colours contrast more than the old ones.
"""
import numpy as np
from PIL import Image, ImageFilter


def _lum(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def _sstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _hue(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn + 1e-6
    return np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60


def _blur(arr, r):
    return np.asarray(Image.fromarray(arr).filter(ImageFilter.GaussianBlur(r))).astype(np.float32)


def _u8(x):
    return (np.clip(x, 0, 1) * 255).astype(np.uint8)


class Recolor:
    # original backdrop: crimson wall (blue/(red+blue) ~0.145), purple floor (~0.37+)
    WALL_RB, FLOOR_RB = 0.145, 0.37
    WALL_Y, FLOOR_Y = 40.0, 22.0

    def __init__(self, clean_rgb, wall_rgb, floor_rgb, horizon_soften=24):
        cl = _blur(np.asarray(clean_rgb, dtype=np.uint8), 6)
        self.Yc = _lum(cl) + 1e-3
        rb = cl[..., 2] / (cl[..., 0] + cl[..., 2] + 1e-3)
        w0 = np.clip((rb - self.WALL_RB) / (self.FLOOR_RB - self.WALL_RB), 0, 1)
        w = _blur(_u8(w0), horizon_soften) / 255
        w = (w * w * (3 - 2 * w))[..., None]
        yref = self.WALL_Y * (1 - w0) + self.FLOOR_Y * w0
        wall, floor = np.array(wall_rgb, np.float32), np.array(floor_rgb, np.float32)
        self.T = (wall * (1 - w) + floor * w) * ((self.Yc / yref) ** 0.7)[..., None]
        self.cc_clean = cl / (cl.sum(-1, keepdims=True) + 15)
        self.rng = np.random.default_rng(0)

    def __call__(self, frame_rgb):
        a = np.asarray(frame_rgb, dtype=np.float32)
        ab = _blur(np.asarray(frame_rgb, dtype=np.uint8), 0.8)
        cc = ab / (ab.sum(-1, keepdims=True) + 15)
        dist = np.abs(cc - self.cc_clean).sum(-1)
        Y = _lum(ab)
        rr = Y / self.Yc
        h = _hue(ab)

        # backdrop = same chroma as the clean plate and not much brighter than it
        bg = (1 - _sstep(0.08, 0.18, dist)) * (1 - _sstep(1.25, 1.7, rr))
        # wall/floor-coloured shadows and reflections
        hw = _sstep(265, 290, h) * (1 - _sstep(350, 358, h))
        bg = np.maximum(bg, hw * (1 - _sstep(1.15, 1.6, rr)))
        # pull the subject edge in ~2px so no old-colour rim survives
        fg = Image.fromarray(_u8(1 - bg))
        bg = 1 - _blur(np.asarray(fg.filter(ImageFilter.MinFilter(5))), 1.2) / 255

        # despill the wall's red in a band around the subject edge
        f8 = Image.fromarray(_u8(1 - bg))
        band = (np.asarray(f8.filter(ImageFilter.MaxFilter(9)), np.float32)
                - np.asarray(f8.filter(ImageFilter.MinFilter(13)), np.float32)) / 255
        band = _blur(_u8(band), 2) / 255
        a[..., 0] = a[..., 0] * (1 - band) + np.minimum(a[..., 0], 1.7 * a[..., 1] + 12) * band

        new = self.T * np.minimum(np.clip(rr, 0, 1.1), 1.1 - 0.15 * band)[..., None]  # no bright rim at edges
        out = a * (1 - bg[..., None]) + new * bg[..., None]
        out += self.rng.uniform(-0.6, 0.6, out.shape)  # dither against banding
        return np.clip(out, 0, 255).astype(np.uint8)
