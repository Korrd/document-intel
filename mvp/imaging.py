#!/usr/bin/env python3
"""Page-image handling: size, hash, quality score, and cropping.

Cropping is what makes the "we never throw away the pixels" claim real -- the
escalation path cuts the exact cited region out of the page and re-reads it.

Uses macOS `sips` so there is nothing to install. PNG/JPEG headers are parsed
directly for dimensions.
"""
import hashlib
import pathlib
import struct
import subprocess
import tempfile

SIPS = "/usr/bin/sips"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dimensions(path):
    """(width, height) from the file header. PNG and JPEG."""
    data = pathlib.Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return int(w), int(h)
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    out = subprocess.run([SIPS, "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                         capture_output=True, text=True)
    vals = {}
    for line in out.stdout.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            vals[k.strip()] = v.strip()
    return int(vals.get("pixelWidth", 0)), int(vals.get("pixelHeight", 0))


def to_png(src, dst, max_edge=1600):
    """Normalize any input (incl. HEIC from a phone camera) to a bounded PNG."""
    subprocess.run([SIPS, "-s", "format", "png", "-Z", str(max_edge),
                    str(src), "--out", str(dst)],
                   check=True, capture_output=True, timeout=120)
    return dst


def quality_score(path):
    """A cheap, deterministic scan-quality proxy: resolution and file entropy.

    Not a model call. Its job is to decide whether a page is worth escalating
    and to give drift monitoring something to trend.
    """
    w, h = dimensions(path)
    size = pathlib.Path(path).stat().st_size
    megapixels = (w * h) / 1e6 if w and h else 0.0
    bpp = (size * 8) / (w * h) if w and h else 0.0
    res = min(1.0, megapixels / 1.6)                 # ~A4 at 150dpi == 1.5MP
    detail = min(1.0, bpp / 1.2)
    score = round(0.65 * res + 0.35 * detail, 3)
    notes = []
    if megapixels < 0.7:
        notes.append("low resolution (%.2f MP) -- OCR risk on small print" % megapixels)
    if bpp < 0.25:
        notes.append("very low detail per pixel -- heavy compression or blank page")
    return dict(score=score, width=w, height=h, megapixels=round(megapixels, 2),
                bits_per_pixel=round(bpp, 3), bytes=size,
                notes="; ".join(notes) or "acceptable")


def crop(path, bbox, out_path=None, pad=0.012, upscale=2):
    """Crop a normalized bbox out of a page image.

    bbox is [x0, y0, x1, y1] on a 0..1000 scale (the scale the vision agent is
    asked to emit). Returns the path to the cropped PNG.
    """
    w, h = dimensions(path)
    if not w or not h:
        raise ValueError("cannot determine image dimensions for %s" % path)
    x0, y0, x1, y1 = [max(0.0, min(1.0, float(v) / 1000.0)) for v in bbox]
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    x0, y0 = max(0.0, x0 - pad), max(0.0, y0 - pad)
    x1, y1 = min(1.0, x1 + pad), min(1.0, y1 + pad)

    left, top = int(x0 * w), int(y0 * h)
    cw, ch = max(16, int((x1 - x0) * w)), max(16, int((y1 - y0) * h))
    cw, ch = min(cw, w - left), min(ch, h - top)

    out_path = pathlib.Path(out_path or tempfile.mktemp(suffix=".png"))
    # sips crops from the centre, so offset the crop with --cropOffset.
    subprocess.run([SIPS, str(path), "--cropToHeightWidth", str(ch), str(cw),
                    "--cropOffset", str(top), str(left), "--out", str(out_path)],
                   check=True, capture_output=True, timeout=120)
    if upscale and upscale > 1 and max(cw, ch) * upscale <= 4000:
        subprocess.run([SIPS, "-z", str(ch * upscale), str(cw * upscale), str(out_path)],
                       check=True, capture_output=True, timeout=120)
    return out_path


if __name__ == "__main__":
    import json
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "docs/stmt-2026-07.png"
    print(json.dumps(quality_score(p), indent=2))
    c = crop(p, [60, 230, 960, 310], out_path="/tmp/crop_test.png")
    print("crop ->", c, dimensions(c))
