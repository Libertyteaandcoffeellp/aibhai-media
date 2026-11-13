#!/usr/bin/env python3
"""AI Bhai reel maker (v2, motion edition).

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
    keywords      words highlighted yellow in captions
    cover         {"lines": [l1, l2, highlight, l4], "chips": [..]}

Motion: animated glowing background with floating particles, a punch-zoom on AI Bhai at every
phrase, a pop-in + shake on the hook, word-by-word karaoke captions, cards that slide in with a
bounce, white flash + whoosh at every section change, a progress bar, and pop sound effects.
Outputs reel.mp4 (1080x1920, 30fps) and cover.jpg. Needs: ffmpeg, Pillow, numpy.
"""
import json, math, os, re, subprocess, sys, tempfile, wave
from functools import lru_cache
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
SR = 44100


def font_path(bold=True):
    cands = [os.path.join(ASSETS, "Poppins-ExtraBold.ttf") if bold else "",
             "/usr/share/fonts/truetype/google-fonts/Poppins-ExtraBold.ttf" if bold else "",
             os.path.join(ASSETS, "Poppins-Bold.ttf"),
             "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise SystemExit("No usable font found")


FX, FB = font_path(True), font_path(False)


@lru_cache(maxsize=512)
def F(size, bold=True):
    return ImageFont.truetype(FX if bold else FB, max(8, int(size)))


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def ease_out(x):
    x = min(1, max(0, x)); return 1 - (1 - x) ** 3


def ease_back(x):
    x = min(1, max(0, x)); c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


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
         "-map", "[out]", "-ar", str(SR), "-ac", "1", dst])
    segs, t = [], 0.0
    for i, (a, b) in enumerate(cuts):
        sa = 0 if i == 0 else KEEP / 2
        sb = (b - a) if i == len(cuts) - 1 else (b - a) - KEEP / 2
        segs.append((t + sa, t + sb)); t += b - a
    return segs, t


def align(phrases, segs, total):
    if len(segs) == len(phrases):
        return segs
    speech = [(a, b) for a, b in segs if b > a]
    tot_speech = sum(b - a for a, b in speech) or total
    lens = [max(1, len(p)) for p in phrases]
    tot_chars = sum(lens)

    def at(x):
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


# ---------- sound effects (synthesised, royalty free) ----------
def sfx_whoosh(dur=0.45):
    n = int(SR * dur); t = np.arange(n) / SR
    noise = np.random.default_rng(1).standard_normal(n)
    # sweep a simple one-pole low-pass cutoff up then down
    cut = 300 + 5000 * np.sin(np.pi * t / dur) ** 2
    out = np.zeros(n); y = 0.0
    for i in range(n):
        a = math.exp(-2 * math.pi * cut[i] / SR); y = (1 - a) * noise[i] + a * y; out[i] = y
    env = np.sin(np.pi * t / dur) ** 1.5
    out = out * env
    return out / (np.abs(out).max() + 1e-9) * 0.55


def sfx_pop(freq=880, dur=0.09):
    n = int(SR * dur); t = np.arange(n) / SR
    f = freq * (1 + 0.6 * np.exp(-t * 60))
    out = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 45)
    return out * 0.5


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


# ---------- drawing helpers ----------
def make_background():
    g = np.linspace(0, 1, H)[:, None]
    top, bot = np.array([10, 30, 92]), np.array([2, 10, 36])
    img = (top * (1 - g) + bot * g)[:, None, :].repeat(W, axis=1)
    base = Image.fromarray(img.astype(np.uint8)[:, :, :3].reshape(H, W, 3), "RGB")
    return base


def make_glow(size, color, strength):
    yy, xx = np.mgrid[0:size, 0:size]
    r = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2) / (size / 2)
    a = np.clip(1 - r, 0, 1) ** 2 * strength
    arr = np.zeros((size, size, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = color
    arr[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def star(d, cx, cy, r, color):
    pts = []
    for k in range(8):
        ang = math.pi / 4 * k - math.pi / 2
        rr = r if k % 2 == 0 else r * 0.32
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=color)


def build(spec_path, vo_path, outdir):
    spec = json.load(open(spec_path))
    phrases = spec["phrases"]
    keywords = set(spec.get("keywords", []))
    tmp = tempfile.mkdtemp()
    vo = os.path.join(tmp, "vo.wav")
    segs, total = tighten(vo_path, vo)
    times = align(phrases, segs, total)
    nfr = int(math.ceil(total * FPS))

    # caption chunks (<=3 words) with per-word timing
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
            wt, acc = [], tt
            wl = sum(len(w) + 1 for w in g)
            for w in g:
                wd = dd * (len(w) + 1) / wl; wt.append((acc, acc + wd)); acc += wd
            chunks.append((tt, tt + dd, g, wt)); tt += dd

    # mouth states (lip-sync): 0 closed, 1 small, 2 medium, 3 wide, 4 "O"
    with wave.open(vo) as wv:
        raw = np.frombuffer(wv.readframes(wv.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    spf = SR // FPS
    rms = np.zeros(nfr); cen = np.zeros(nfr)
    freqs = np.fft.rfftfreq(spf, 1 / SR)
    win = np.hanning(spf)
    for i in range(nfr):
        seg = raw[i * spf:(i + 1) * spf]
        if len(seg) < spf:
            seg = np.pad(seg, (0, spf - len(seg)))
        rms[i] = np.sqrt(np.mean(seg ** 2) + 1e-12)
        mag = np.abs(np.fft.rfft(seg * win))
        band = (freqs > 150) & (freqs < 4000)
        cen[i] = (freqs[band] * mag[band]).sum() / (mag[band].sum() + 1e-9)
    db = 20 * np.log10(rms + 1e-9)
    peak = np.percentile(db, 95)
    w = int(0.6 * FPS)
    local_max = np.array([rms[max(0, i - w):i + w + 1].max() for i in range(nfr)])
    lvl = rms / (local_max + 1e-9)
    voiced = db > peak - 26
    cen_lo = np.percentile(cen[voiced], 30) if voiced.any() else 0
    state = np.zeros(nfr, dtype=int)
    for i in range(nfr):
        if not voiced[i] or lvl[i] < 0.22:
            state[i] = 0
        elif lvl[i] < 0.45:
            state[i] = 1
        elif lvl[i] < 0.75:
            state[i] = 2
        else:
            state[i] = 4 if cen[i] < cen_lo else 3
    for i in range(1, nfr - 1):  # drop single-frame flicker
        if state[i - 1] == state[i + 1] != state[i]:
            state[i] = state[i - 1]

    cut_path = lambda k: os.path.join(ASSETS, f"cut_{k}.png")
    src = [Image.open(cut_path(k)).convert("RGBA") for k in "ABCDE"]
    sc = lambda h: [m.resize((int(m.width * h / m.height), h), Image.LANCZOS) for m in src]
    BIG, SMALL = sc(1500), sc(760)

    nh, ne = spec["hook_phrases"], spec["end_phrases"]
    T_MID = times[nh][0] - 0.12 if nh < len(times) else total
    T_END = times[len(times) - ne][0] - 0.12 if ne else total + 1
    cards = [(times[c["at"]][0] - 0.12, c) for c in spec.get("cards", [])]
    phrase_starts = [a for a, _ in times]
    flashes = sorted(set([T_MID, T_END] + [ct for ct, _ in cards]))

    base_bg = make_background()
    glows = [make_glow(1100, (124, 58, 237), 0.55), make_glow(900, (250, 204, 21), 0.22), make_glow(800, (56, 189, 248), 0.25)]
    rng = np.random.default_rng(7)
    parts = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(3, 8), rng.uniform(25, 70), rng.uniform(0, 6.28)) for _ in range(34)]

    def background(t):
        img = base_bg.copy()
        for k, gl in enumerate(glows):
            gx = W / 2 + math.sin(t * (0.35 + 0.17 * k) + k * 2.1) * 380 - gl.width / 2
            gy = H * (0.25 + 0.3 * k) + math.cos(t * (0.28 + 0.11 * k) + k) * 260 - gl.height / 2
            img.paste(gl, (int(gx), int(gy)), gl)
        d = ImageDraw.Draw(img)
        for (x, y, r, sp, ph) in parts:
            yy = (y - t * sp) % H
            xx = x + math.sin(t * 0.8 + ph) * 18
            a = 0.35 + 0.35 * math.sin(t * 2 + ph)
            c = tuple(int(BG[i] * (1 - a) + (255, 255, 255)[i] * a) for i in range(3))
            d.ellipse((xx - r, yy - r, xx + r, yy + r), fill=c)
        return img

    def punch(t):
        last = max([s for s in phrase_starts if s <= t] or [0])
        p = (t - last) / 0.28
        return 1 + 0.07 * (1 - ease_out(p)) if p < 1 else 1.0

    def caption(img, chunk, t, y):
        a, b, words, wt = chunk
        pop = 0.82 + 0.18 * ease_back((t - a) / 0.14)
        d = ImageDraw.Draw(img)
        act = None
        for k, (wa, wb) in enumerate(wt):
            if wa <= t < wb:
                act = k
        if act is None:
            act = len(words) - 1 if t >= wt[-1][0] else 0
        size = 80
        while True:
            fonts = [F(size * pop * (1.12 if k == act else 1.0)) for k in range(len(words))]
            widths = [d.textlength(w, font=f) for w, f in zip(words, fonts)]
            gap = 22
            tw = sum(widths) + gap * (len(words) - 1) + 32
            if tw <= 980 or size <= 46:
                break
            size -= 4
        x = (W - tw) / 2 + 16
        for k, (w, f, ww) in enumerate(zip(words, fonts, widths)):
            cx = x + ww / 2
            key = re.sub(r"[^\w@]", "", w) in keywords
            if k == act:
                d.rounded_rectangle((cx - ww / 2 - 14, y - 56, cx + ww / 2 + 14, y + 54), 18, fill=YEL if not key else WHITE)
                d.text((cx, y), w, font=f, fill=BG, anchor="mm")
            else:
                d.text((cx, y), w, font=f, fill=YEL if key else WHITE, stroke_width=7, stroke_fill=(0, 0, 0), anchor="mm")
            x += ww + gap

    def header(img, top, bottom, t0, t, y=160):
        d = ImageDraw.Draw(img)
        p = ease_back((t - t0) / 0.38)
        shake = math.sin((t - t0) * 70) * 12 * max(0, 1 - (t - t0) / 0.5)
        s1 = 96
        while d.textlength(top, font=F(s1)) > 960 and s1 > 50: s1 -= 4
        s2 = 84
        while d.textlength(bottom, font=F(s2)) > 960 and s2 > 44: s2 -= 4
        d.text((W / 2 + shake, y), top, font=F(s1 * max(0.3, p)), fill=YEL, stroke_width=8, stroke_fill=(0, 0, 0), anchor="mm")
        p2 = ease_back((t - t0 - 0.12) / 0.38)
        if p2 > 0:
            d.text((W / 2 - shake, y + 122), bottom, font=F(s2 * max(0.3, p2)), fill=WHITE, stroke_width=8, stroke_fill=(0, 0, 0), anchor="mm")
        # sparkles
        for k, (sx, sy) in enumerate([(110, y - 40), (W - 110, y + 10), (170, y + 150), (W - 170, y + 175)]):
            pulse = 0.6 + 0.4 * math.sin(t * 6 + k * 1.7)
            star(d, sx, sy, 26 * pulse * min(1, p), YEL if k % 2 == 0 else WHITE)

    def chip(d, x, y, s):
        f = F(40, False); w = d.textlength(s, font=f) + 56
        d.rounded_rectangle((x, y, x + w, y + 70), 35, fill=PURPLE)
        d.text((x + w / 2, y + 35), s, font=f, fill=WHITE, anchor="mm")
        return w

    def card_image(c):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        x0, y0, x1, y1 = 70, 230, W - 70, 1080
        d.rounded_rectangle((x0 + 12, y0 + 16, x1 + 12, y1 + 16), 48, fill=(0, 0, 0, 110))
        d.rounded_rectangle((x0, y0, x1, y1), 48, fill=CARD + (255,), outline=YEL, width=6)
        cy = y0 + 150
        if c.get("num"):
            d.ellipse((x0 + 60, cy - 70, x0 + 200, cy + 70), fill=YEL)
            d.text((x0 + 130, cy), str(c["num"]), font=F(96), fill=BG, anchor="mm")
            s = 112
            while d.textlength(c["title"], font=F(s)) > 640 and s > 50: s -= 4
            d.text((x0 + 240, cy), c["title"], font=F(s), fill=WHITE, anchor="lm")
        else:
            s = 96
            while d.textlength(c["title"], font=F(s)) > 860 and s > 50: s -= 4
            d.text((W / 2, cy), c["title"], font=F(s), fill=YEL, anchor="mm")
        ly = y0 + 360
        for ln in c.get("lines", []):
            s = 64
            while d.textlength(ln, font=F(s, False)) > 860 and s > 36: s -= 4
            d.text((W / 2, ly), ln, font=F(s, False), fill=WHITE, anchor="mm"); ly += 100
        cx = x0 + 70
        for chp in c.get("chips", []):
            cx += chip(d, cx, y1 - 150, chp) + 24
        return img

    card_imgs = [card_image(c) for _, c in cards]

    os.makedirs(outdir, exist_ok=True)
    silent_mp4 = os.path.join(tmp, "v.mp4")
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                          "-crf", "20", "-pix_fmt", "yuv420p", silent_mp4], stdin=subprocess.PIPE)
    for i in range(nfr):
        t = i / FPS
        img = background(t)
        s = state[i]
        mid = T_MID <= t < T_END and cards
        pz = punch(t)
        if not mid:
            start = 0 if t < T_MID else T_END
            z = ease_out((t - start) / 0.45)
            ch = BIG[s]
            scale = (0.9 + 0.1 * z) * pz * (1 + 0.015 * math.sin(t * 1.3))
            cw, chh = int(ch.width * scale), int(ch.height * scale)
            chs = ch.resize((cw, chh), Image.BILINEAR)
            sway = int(math.sin(t * 1.7) * 14)
            img.paste(chs, ((W - cw) // 2 + sway, H - chh + 90 + int(8 * math.sin(t * 2.4))), chs)
            if t < T_MID:
                header(img, *spec["hook"], 0.0, t)
            else:
                header(img, *spec["end"], T_END, t)
                d = ImageDraw.Draw(img)
                pulse = 1 + 0.06 * math.sin(t * 6)
                d.text((W / 2, 430), "Follow @aibhai_hindi", font=F(58 * pulse, False), fill=WHITE, stroke_width=6, stroke_fill=(0, 0, 0), anchor="mm")
            cap_y = 1440
        else:
            idx = max([k for k, (ct, _) in enumerate(cards) if t >= ct] or [0])
            ct = cards[idx][0]
            pr = (t - ct) / 0.42
            ch = SMALL[s]
            scale = pz
            chs = ch.resize((int(ch.width * scale), int(ch.height * scale)), Image.BILINEAR)
            img.paste(chs, (W - chs.width + 120, H - chs.height + 40 + int(5 * math.sin(t * 2.4))), chs)
            off = int((1 - ease_back(pr)) * W * 1.05)
            if pr < 1 and idx > 0:  # previous card slides out to the left
                prev_off = -int(ease_out(pr) * W * 1.05)
                img.paste(card_imgs[idx - 1], (prev_off, 0), card_imgs[idx - 1])
            img.paste(card_imgs[idx], (off, int(8 * math.sin(t * 2))), card_imgs[idx])
            cap_y = 1180
        for chunk in chunks:
            if chunk[0] <= t < chunk[1]:
                caption(img, chunk, t, cap_y); break
        # progress bar
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 10), fill=(255, 255, 255, 0))
        d.rectangle((0, 0, int(W * t / total), 10), fill=YEL)
        # flash on section changes
        for fl in flashes:
            if 0 <= t - fl < 0.16:
                a = 0.55 * (1 - (t - fl) / 0.16)
                img = Image.blend(img, Image.new("RGB", (W, H), WHITE), a)
        p.stdin.write(img.tobytes())
    p.stdin.close(); p.wait()

    # sound effects track
    n = int(total * SR) + SR
    fx = np.zeros(n)
    wh, pop, pop2 = sfx_whoosh(), sfx_pop(900), sfx_pop(1300, 0.07)

    def add(snd, t0):
        a = int(max(0, t0) * SR); b = min(n, a + len(snd)); fx[a:b] += snd[:b - a]

    add(pop2, 0.02)
    for fl in flashes:
        add(wh, fl - 0.2)
    for ct, _ in cards:
        add(pop, ct + 0.32)
    add(pop2, T_END + 0.3)
    fxp = os.path.join(tmp, "fx.wav"); write_wav(fxp, fx * 0.45)

    out_mp4 = os.path.join(outdir, "reel.mp4")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", silent_mp4, "-i", vo, "-i", fxp,
         "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
         "-shortest", "-movflags", "+faststart", out_mp4])

    # cover
    cv = spec.get("cover", {})
    lines = cv.get("lines") or [spec["hook"][0], "", spec["hook"][1], ""]
    img = background(1.0)
    ch = src[2].resize((int(src[2].width * 1060 / src[2].height), 1060), Image.LANCZOS)
    img.paste(ch, ((W - ch.width) // 2 + 150, H - ch.height), ch)
    d = ImageDraw.Draw(img)
    y = 260
    for k, ln in enumerate(lines):
        if not ln:
            continue
        if k == 2:
            s = 84
            while d.textlength(ln, font=F(s)) > 940 and s > 40: s -= 4
            d.rounded_rectangle((60, y - 60, 60 + d.textlength(ln, font=F(s)) + 50, y + 60), 24, fill=YEL)
            d.text((85, y), ln, font=F(s), fill=BG, anchor="lm"); y += 130
        else:
            s = 150 if k < 2 else 110
            while d.textlength(ln, font=F(s)) > 940 and s > 40: s -= 4
            d.text((70, y), ln, font=F(s), fill=YEL if k == 1 else WHITE, stroke_width=8, stroke_fill=(0, 0, 0), anchor="lm")
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
