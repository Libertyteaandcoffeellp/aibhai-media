#!/usr/bin/env python3
"""AI Bhai reel maker.

Usage:
    python3 pipeline/make_reel.py reels/<id>/spec.json reels/<id>/vo.mp3 reels/<id>/

Spec JSON fields:
    id            reel id, e.g. "002"
    phrases       list of spoken phrases, in order (exact voiceover text split into phrases)
    hook          [top line, bottom line]   shown in the opening section
    end           [top line, bottom line]   shown in the closing section
    hook_phrases  how many phrases belong to the opening section (AI Bhai full screen)
    end_phrases   how many phrases belong to the closing section
    cards         list of {"at": phrase index, "title", "num" (or null), "lines": [..], "chips": [..]}
                  shown in the middle section (AI Bhai small in the corner)
    keywords      words highlighted yellow in captions
    cover         {"lines": [l1, l2, highlight, l4], "chips": [..]}

Outputs reel.mp4 (1080x1920, 30fps, captions, lip-synced mouth) and cover.jpg.
Needs: ffmpeg, Pillow, numpy.
"""
import json, math, os, re, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
W, H, FPS = 1080, 1920, 30
BG = (3, 20, 63)
YEL = (250, 204, 21)
WHITE = (255, 255, 255)
PURPLE = (124, 58, 237)
CARD = (15, 32, 82)
KEEP = 0.25  # pause length kept between phrases (seconds)


def font_path(bold=True):
    cands = [os.path.join(ASSETS, "Poppins-ExtraBold.ttf" if bold else "Poppins-Bold.ttf"),
             "/usr/share/fonts/truetype/google-fonts/Poppins-ExtraBold.ttf" if bold else "",
             "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
             os.path.join(ASSETS, "Poppins-Bold.ttf"),
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise SystemExit("No usable font found")


FX, FB = font_path(True), font_path(False)
F = lambda s, bold=True: ImageFont.truetype(FX if bold else FB, s)


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def silences(path, noise="-35dB", d=0.35):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", f"silencedetect=noise={noise}:d={d}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    vals = [float(x) for x in re.findall(r"silence_(?:start|end): ([0-9.]+)", out)]
    if len(vals) % 2:
        vals = vals[:-1]
    return list(zip(vals[0::2], vals[1::2]))


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout)


def tighten(src, dst):
    """Cut every long pause down to KEEP seconds; return speech segments in the new timeline."""
    dur = duration(src)
    sil = [(s, e) for s, e in silences(src) if s > 0.05 and e < dur - 0.05]
    lead = [e for s, e in silences(src) if s <= 0.05]
    start = max(0.0, (lead[0] - 0.05)) if lead else 0.0
    cuts, cur = [], start
    for s, e in sil:
        cuts.append((cur, s + KEEP / 2)); cur = e - KEEP / 2
    cuts.append((cur, dur))
    parts, labels = [], []
    for i, (a, b) in enumerate(cuts):
        parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,"
                     f"afade=t=out:st={max(b - a - 0.01, 0):.3f}:d=0.01[s{i}]")
        labels.append(f"[s{i}]")
    fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(cuts)}:v=0:a=1,loudnorm=I=-14:TP=-1.0:LRA=7[out]"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-filter_complex", fc,
         "-map", "[out]", "-ar", "44100", "-b:a", "192k", dst])
    segs, t = [], 0.0
    for i, (a, b) in enumerate(cuts):
        sa = 0 if i == 0 else KEEP / 2
        sb = (b - a) if i == len(cuts) - 1 else (b - a) - KEEP / 2
        segs.append((t + sa, t + sb)); t += b - a
    return segs, t


def align(phrases, segs, total):
    """Give every phrase a (start, end) time."""
    if len(segs) == len(phrases):
        return segs
    # fallback: spread phrases over the speech time by character share
    speech = [(a, b) for a, b in segs if b > a]
    tot_speech = sum(b - a for a, b in speech) or total
    lens = [max(1, len(p)) for p in phrases]
    tot_chars = sum(lens)

    def at(x):  # x seconds of speech -> timeline position
        acc = 0.0
        for a, b in speech:
            if acc + (b - a) >= x:
                return a + (x - acc)
            acc += b - a
        return speech[-1][1] if speech else x

    out, acc = [], 0.0
    for L in lens:
        s = at(acc); acc += tot_speech * L / tot_chars
        out.append((s, at(acc)))
    return out


def stroke_text(d, xy, s, f, fill, sw=6, anchor="mm"):
    d.text(xy, s, font=f, fill=fill, stroke_width=sw, stroke_fill=(0, 0, 0), anchor=anchor)


def fit(d, s, size, maxw=960, bold=True):
    f = F(size, bold)
    while d.textlength(s, font=f) > maxw and f.size > 40:
        f = F(f.size - 4, bold)
    return f


def build(spec_path, vo_path, outdir):
    spec = json.load(open(spec_path))
    phrases = spec["phrases"]
    keywords = set(spec.get("keywords", []))
    tmp = tempfile.mkdtemp()
    vo = os.path.join(tmp, "vo.mp3")
    segs, total = tighten(vo_path, vo)
    times = align(phrases, segs, total)

    # captions: chunks of <=3 words
    chunks = []
    for (a, b), ph in zip(times, phrases):
        words = ph.split()
        groups = [words[i:i + 3] for i in range(0, len(words), 3)]
        if len(groups) > 1 and len(groups[-1]) == 1:
            last = groups.pop(); groups[-1] = groups[-1] + last
        tl = sum(len(" ".join(g)) for g in groups) or 1
        tt = a
        for g in groups:
            dd = (b - a) * len(" ".join(g)) / tl
            chunks.append((tt, tt + dd, g)); tt += dd

    # mouth states from loudness
    raw_path = os.path.join(tmp, "vo.raw")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", vo, "-ac", "1", "-ar", "16000", "-f", "s16le", "-y", raw_path])
    raw = np.fromfile(raw_path, dtype=np.int16).astype(np.float32) / 32768
    spf = 16000 // FPS
    nfr = int(math.ceil(total * FPS))
    rms = np.array([np.sqrt(np.mean(raw[i * spf:(i + 1) * spf] ** 2) + 1e-12) for i in range(nfr)])
    db = 20 * np.log10(rms + 1e-9)
    peak = np.percentile(db, 95)
    state = np.where(db < peak - 22, 0, np.where(db < peak - 5, 1, 2))
    for i in range(1, nfr - 1):
        if state[i - 1] == state[i + 1] != state[i]:
            state[i] = state[i - 1]

    mouths = [Image.open(os.path.join(ASSETS, f"frame_{k}.png")).convert("RGB") for k in "ABC"]
    sc = lambda h: [m.resize((int(m.width * h / m.height), h), Image.LANCZOS) for m in mouths]
    BIG, SMALL = sc(1500), sc(760)

    nh, ne = spec["hook_phrases"], spec["end_phrases"]
    T_MID = times[nh][0] - 0.12 if nh < len(times) else total
    T_END = times[len(times) - ne][0] - 0.12 if ne else total + 1
    cards = [(times[c["at"]][0] - 0.12, c) for c in spec.get("cards", [])]

    def caption(img, words, y):
        d = ImageDraw.Draw(img)
        f = F(78)
        while True:
            tw = sum(d.textlength(w, font=f) for w in words) + d.textlength(" ", font=f) * (len(words) - 1)
            if tw <= 960 or f.size <= 50:
                break
            f = F(f.size - 4)
        sp = d.textlength(" ", font=f)
        x = (W - tw) / 2
        for w in words:
            c = YEL if re.sub(r"[^\w@]", "", w) in keywords else WHITE
            d.text((x, y), w, font=f, fill=c, stroke_width=7, stroke_fill=(0, 0, 0), anchor="lm")
            x += d.textlength(w, font=f) + sp

    def header(d, top, bottom, y=150):
        stroke_text(d, (W / 2, y), top, fit(d, top, 96), YEL, 8)
        stroke_text(d, (W / 2, y + 120), bottom, fit(d, bottom, 84), WHITE, 8)

    def chip(d, x, y, s):
        f = F(40, False); w = d.textlength(s, font=f) + 56
        d.rounded_rectangle((x, y, x + w, y + 70), 35, fill=PURPLE)
        d.text((x + w / 2, y + 35), s, font=f, fill=WHITE, anchor="mm")
        return w

    def card_layer(c, prog):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        off = int((1 - prog) * 140)
        x0, y0, x1, y1 = 70, 230 + off, W - 70, 1080 + off
        d.rounded_rectangle((x0, y0, x1, y1), 48, fill=CARD + (255,), outline=YEL, width=5)
        cy = y0 + 150
        if c.get("num"):
            d.ellipse((x0 + 60, cy - 70, x0 + 200, cy + 70), fill=YEL)
            d.text((x0 + 130, cy), str(c["num"]), font=F(96), fill=BG, anchor="mm")
            d.text((x0 + 240, cy), c["title"], font=fit(d, c["title"], 112, 640), fill=WHITE, anchor="lm")
        else:
            d.text((W / 2, cy), c["title"], font=fit(d, c["title"], 96, 860), fill=YEL, anchor="mm")
        ly = y0 + 360
        for ln in c.get("lines", []):
            d.text((W / 2, ly), ln, font=fit(d, ln, 64, 860, False), fill=WHITE, anchor="mm"); ly += 100
        cx = x0 + 70
        for ch in c.get("chips", []):
            cx += chip(d, cx, y1 - 150, ch) + 24
        if prog < 1:
            img.putalpha(img.getchannel("A").point(lambda v: int(v * prog)))
        return img

    os.makedirs(outdir, exist_ok=True)
    out_mp4 = os.path.join(outdir, "reel.mp4")
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", vo, "-c:v", "libx264", "-preset", "veryfast",
                          "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
                          "-movflags", "+faststart", out_mp4], stdin=subprocess.PIPE)
    for i in range(nfr):
        t = i / FPS
        img = Image.new("RGB", (W, H), BG)
        s = state[i]
        mid = T_MID <= t < T_END and cards
        if not mid:
            start = 0 if t < T_MID else T_END
            z = min(1, (t - start) / 0.35)
            ch = BIG[s]
            scale = 0.94 + 0.06 * z
            if scale < 1:
                ch = ch.resize((int(ch.width * scale), int(ch.height * scale)), Image.BILINEAR)
            img.paste(ch, ((W - ch.width) // 2, H - ch.height + 60 + int(6 * math.sin(t * 2.4))))
            d = ImageDraw.Draw(img)
            if t < T_MID:
                header(d, *spec["hook"])
            else:
                header(d, *spec["end"])
                stroke_text(d, (W / 2, 420), "Follow @aibhai_hindi", F(58, False), WHITE, 6)
            cap_y = 1440
        else:
            idx = max([k for k, (ct, _) in enumerate(cards) if t >= ct] or [0])
            ct, c = cards[idx]
            lay = card_layer(c, min(1, max(0, (t - ct) / 0.3)))
            ch = SMALL[s]
            img.paste(ch, (W - ch.width + 120, H - ch.height + 40 + int(5 * math.sin(t * 2.4))))
            img.paste(lay, (0, 0), lay)
            cap_y = 1165
        for a, b, g in chunks:
            if a <= t < b:
                caption(img, g, cap_y); break
        p.stdin.write(img.tobytes())
    p.stdin.close(); p.wait()

    # cover
    cv = spec.get("cover", {})
    lines = cv.get("lines") or [spec["hook"][0], "", spec["hook"][1], ""]
    img = Image.new("RGB", (W, H), BG)
    ch = mouths[2].resize((int(mouths[2].width * 1060 / mouths[2].height), 1060), Image.LANCZOS)
    img.paste(ch, ((W - ch.width) // 2 + 150, H - ch.height))
    d = ImageDraw.Draw(img)
    y = 260
    for k, ln in enumerate(lines):
        if not ln:
            continue
        if k == 2:  # highlight box
            f = fit(d, ln, 84, 940)
            d.rounded_rectangle((60, y - 60, 60 + d.textlength(ln, font=f) + 50, y + 60), 24, fill=YEL)
            d.text((85, y), ln, font=f, fill=BG, anchor="lm"); y += 130
        else:
            f = fit(d, ln, 150 if k < 2 else 110, 940)
            d.text((70, y), ln, font=f, fill=YEL if k == 1 else WHITE, stroke_width=8, stroke_fill=(0, 0, 0), anchor="lm")
            y += 160 if k < 2 else 130
    x = 70
    for c in cv.get("chips", []):
        fc = F(44, False); w = d.textlength(c, font=fc) + 60
        d.rounded_rectangle((x, y, x + w, y + 76), 38, fill=PURPLE)
        d.text((x + w / 2, y + 38), c, font=fc, fill=WHITE, anchor="mm"); x += w + 22
    img.save(os.path.join(outdir, "cover.jpg"), quality=92)
    print(json.dumps({"reel": out_mp4, "seconds": round(total, 2), "phrases": len(phrases), "segments": len(segs)}))


if __name__ == "__main__":
    build(*sys.argv[1:4])
