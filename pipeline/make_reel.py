#!/usr/bin/env python3
"""AI Bhai reel maker (motion version).

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

Motion: animated background (gradient, moving grid, glow, particles), beat bounce on the
character, punch-zoom + flash + whoosh on every section/card change, pop-in hook text,
pop captions, bouncy card slide-ins, progress bar, soft background beat.
Outputs reel.mp4 (1080x1920, 30fps) and cover.jpg. Needs: ffmpeg, Pillow, numpy.
"""
import json, math, os, re, subprocess, sys, tempfile, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
W, H, FPS = 1080, 1920, 30
BG = (3, 20, 63)
YEL = (250, 204, 21)
WHITE = (255, 255, 255)
PURPLE = (124, 58, 237)
CARD = (15, 32, 82)
KEEP = 0.25
SR = 44100


def font_path(bold=True):
    cands = [os.path.join(ASSETS, "Poppins-ExtraBold.ttf") if bold else "",
             "/usr/share/fonts/truetype/google-fonts/Poppins-ExtraBold.ttf" if bold else "",
             "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
             os.path.join(ASSETS, "Poppins-Bold.ttf"),
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise SystemExit("No usable font found")


FX, FB = font_path(True), font_path(False)
_fc = {}


def F(s, bold=True):
    k = (s, bold)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FX if bold else FB, s)
    return _fc[k]


def ease_out_back(t):
    t = min(max(t, 0.0), 1.0)
    c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


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


# ---------------- audio: soft beat + whooshes ----------------
def synth_bed(total, hits, seed=7):
    rng = np.random.default_rng(seed)
    n = int(total * SR) + SR
    out = np.zeros(n, np.float32)
    bpm = 96.0; beat = 60.0 / bpm
    tk = np.arange(int(0.18 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 + 80 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 18)
    th = np.arange(int(0.05 * SR)) / SR
    hat = rng.standard_normal(len(th)) * np.exp(-th * 90)
    hat = np.diff(np.concatenate([[0], hat]))  # crude high-pass
    t = 0.0; k = 0
    while t < total:
        i = int(t * SR)
        if k % 2 == 0:
            out[i:i + len(kick)] += 0.55 * kick[: n - i]
        j = int((t + beat / 2) * SR)
        if j < n:
            out[j:j + len(hat)] += 0.12 * hat[: n - j]
        t += beat; k += 1
    # soft pad (two detuned sines, slow swell)
    tt = np.arange(n) / SR
    pad = (np.sin(2 * np.pi * 110 * tt) + np.sin(2 * np.pi * 164.8 * tt) * 0.6 + np.sin(2 * np.pi * 220.5 * tt) * 0.3)
    pad *= 0.035 * (0.6 + 0.4 * np.sin(2 * np.pi * tt / (beat * 8)))
    out += pad.astype(np.float32)
    out *= 0.35  # keep the bed well under the voice
    tw = np.arange(int(0.35 * SR)) / SR
    noise = rng.standard_normal(len(tw))
    env = np.sin(np.pi * tw / tw[-1]) ** 2
    whoosh = np.convolve(noise, np.ones(12) / 12, mode="same") * env * 0.5
    tp = np.arange(int(0.08 * SR)) / SR
    pop = np.sin(2 * np.pi * (900 - 500 * tp / tp[-1]) * tp) * np.exp(-tp * 45) * 0.35
    for h, kind in hits:
        i = max(0, int((h - (0.18 if kind == "whoosh" else 0)) * SR))
        snd = whoosh if kind == "whoosh" else pop
        out[i:i + len(snd)] += snd[: max(0, n - i)]
    out = out[: int(total * SR)]
    return np.clip(out, -1, 1)


def write_wav(path, data):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((data * 32767).astype(np.int16).tobytes())


# ---------------- visuals ----------------
def make_background():
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.42) / H) ** 2)
    c0 = np.array([14, 44, 112.0]); c1 = np.array([2, 10, 36.0])
    k = np.clip(r / 0.75, 0, 1)[..., None]
    base = (c0 * (1 - k) + c1 * k).astype(np.uint8)
    base = Image.fromarray(base, "RGB")
    grid = Image.new("RGBA", (W, H + 120), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    for x in range(0, W + 1, 120):
        g.line([(x, 0), (x, H + 120)], fill=(90, 130, 255, 22), width=2)
    for y in range(0, H + 121, 120):
        g.line([(0, y), (W, y)], fill=(90, 130, 255, 22), width=2)
    glow = Image.new("RGBA", (700, 700), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((150, 150, 550, 550), fill=(250, 204, 21, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    glow2 = Image.new("RGBA", (700, 700), (0, 0, 0, 0))
    ImageDraw.Draw(glow2).ellipse((150, 150, 550, 550), fill=(124, 58, 237, 90))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(110))
    return base, grid, glow, glow2


def build(spec_path, vo_path, outdir):
    spec = json.load(open(spec_path))
    phrases = spec["phrases"]
    keywords = set(spec.get("keywords", []))
    tmp = tempfile.mkdtemp()
    vo = os.path.join(tmp, "vo.wav")
    segs, total = tighten(vo_path, vo)
    times = align(phrases, segs, total)

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

    # loudness -> mouth state + bounce envelope
    raw = np.frombuffer(wave.open(vo).readframes(10 ** 9), dtype=np.int16).astype(np.float32) / 32768
    spf = SR // FPS
    nfr = int(math.ceil(total * FPS))
    rms = np.array([np.sqrt(np.mean(raw[i * spf:(i + 1) * spf] ** 2) + 1e-12) if i * spf < len(raw) else 1e-6
                    for i in range(nfr)])
    db = 20 * np.log10(rms + 1e-9)
    peak = np.percentile(db, 95)
    state = np.where(db < peak - 22, 0, np.where(db < peak - 5, 1, 2))
    for i in range(1, nfr - 1):
        if state[i - 1] == state[i + 1] != state[i]:
            state[i] = state[i - 1]
    env = np.clip((db - (peak - 25)) / 25, 0, 1)
    sm = np.zeros_like(env)
    for i in range(nfr):
        sm[i] = max(env[i], sm[i - 1] * 0.82 if i else 0)

    cut = [Image.open(os.path.join(ASSETS, f"cut_{k}.png")).convert("RGBA") for k in "ABC"]
    sc = lambda h: [m.resize((int(m.width * h / m.height), h), Image.LANCZOS) for m in cut]
    BIG, SMALL = sc(1380), sc(700)
    def glow_of(img):
        a = img.getchannel("A").filter(ImageFilter.GaussianBlur(28))
        g = Image.new("RGBA", img.size, YEL + (0,)); g.putalpha(a.point(lambda v: int(v * 0.45)))
        return g
    BIG_GLOW, SMALL_GLOW = glow_of(BIG[0]), glow_of(SMALL[0])
    bg_base, bg_grid, glow_y, glow_p = make_background()
    rng = np.random.default_rng(3)
    parts = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(2, 6), rng.uniform(20, 70)) for _ in range(28)]

    nh, ne = spec["hook_phrases"], spec["end_phrases"]
    T_MID = times[nh][0] - 0.12 if nh < len(times) else total
    T_END = times[len(times) - ne][0] - 0.12 if ne else total + 1
    cards = [(times[c["at"]][0] - 0.12, c) for c in spec.get("cards", [])]
    has_mid = bool(cards)
    events = [0.0] + ([T_MID] if has_mid else []) + [ct for ct, _ in cards[1:]] + ([T_END] if T_END < total else [])
    hits = [(e, "whoosh") for e in events[1:]] + [(ct + 0.15, "pop") for ct, c in cards if c.get("num")]

    def text_img(s, f, fill, sw=8):
        d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        l, t, r, b = d0.textbbox((0, 0), s, font=f, stroke_width=sw)
        im = Image.new("RGBA", (r - l + 20, b - t + 20), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((10 - l, 10 - t), s, font=f, fill=fill, stroke_width=sw, stroke_fill=(0, 0, 0))
        return im

    def fit(s, size, maxw=960, bold=True):
        f = F(size, bold)
        d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        while d0.textlength(s, font=f) > maxw and f.size > 40:
            f = F(f.size - 4, bold)
        return f

    hook_imgs = [text_img(spec["hook"][0], fit(spec["hook"][0], 100), YEL), text_img(spec["hook"][1], fit(spec["hook"][1], 86), WHITE)]
    end_imgs = [text_img(spec["end"][0], fit(spec["end"][0], 96), YEL), text_img(spec["end"][1], fit(spec["end"][1], 84), WHITE),
                text_img("Follow @aibhai_hindi", F(58, False), WHITE, 6)]

    def paste_pop(img, layer, cx, cy, k):
        if k <= 0.02:
            return
        w2, h2 = max(1, int(layer.width * k)), max(1, int(layer.height * k))
        l2 = layer.resize((w2, h2), Image.BILINEAR)
        img.paste(l2, (int(cx - w2 / 2), int(cy - h2 / 2)), l2)

    def caption_layer(words):
        f = F(80)
        d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        while True:
            tw = sum(d0.textlength(w, font=f) for w in words) + d0.textlength(" ", font=f) * (len(words) - 1)
            if tw <= 960 or f.size <= 50:
                break
            f = F(f.size - 4)
        im = Image.new("RGBA", (int(tw) + 40, f.size + 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(im); x = 20; sp = d.textlength(" ", font=f)
        for w in words:
            c = YEL if re.sub(r"[^\w@]", "", w) in keywords else WHITE
            d.text((x, im.height / 2), w, font=f, fill=c, stroke_width=8, stroke_fill=(0, 0, 0), anchor="lm")
            x += d.textlength(w, font=f) + sp
        return im
    cap_cache = {}

    def chip(d, x, y, s):
        f = F(40, False); w = d.textlength(s, font=f) + 56
        d.rounded_rectangle((x, y, x + w, y + 70), 35, fill=PURPLE)
        d.text((x + w / 2, y + 35), s, font=f, fill=WHITE, anchor="mm")
        return w

    def card_img(c):
        img = Image.new("RGBA", (W - 140, 850), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        x1, y1 = img.width - 1, img.height - 1
        d.rounded_rectangle((0, 0, x1, y1), 48, fill=CARD + (245,), outline=YEL, width=6)
        cy = 150
        if c.get("num"):
            d.ellipse((60, cy - 70, 200, cy + 70), fill=YEL)
            d.text((130, cy), str(c["num"]), font=F(96), fill=BG, anchor="mm")
            d.text((240, cy), c["title"], font=fit(c["title"], 112, 620), fill=WHITE, anchor="lm")
        else:
            d.text((img.width / 2, cy), c["title"], font=fit(c["title"], 96, 840), fill=YEL, anchor="mm")
        ly = 360
        for ln in c.get("lines", []):
            d.text((img.width / 2, ly), ln, font=fit(ln, 64, 840, False), fill=WHITE, anchor="mm"); ly += 100
        cx = 70
        for chp in c.get("chips", []):
            cx += chip(d, cx, y1 - 150, chp) + 24
        return img
    card_imgs = [card_img(c) for _, c in cards]

    def section_start(t):
        return max([e for e in events if e <= t] or [0.0])

    os.makedirs(outdir, exist_ok=True)
    silent = os.path.join(tmp, "v.mp4")
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                          "-crf", "20", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    stills = {}
    for i in range(nfr):
        t = i / FPS
        s0 = section_start(t); dt = t - s0
        punch = (1 - ease_out(dt / 0.35)) if s0 > 0 or dt < 0.35 else 0.0
        # background
        img = bg_base.copy()
        off = int((t * 40) % 120)
        img.paste(bg_grid.crop((0, 120 - off, W, 120 - off + H)), (0, 0), bg_grid.crop((0, 120 - off, W, 120 - off + H)))
        img.paste(glow_y, (int(W * 0.55 + 160 * math.sin(t * 0.7)) - 350, int(H * 0.35 + 120 * math.cos(t * 0.5)) - 350), glow_y)
        img.paste(glow_p, (int(W * 0.2 + 140 * math.cos(t * 0.6)) - 350, int(H * 0.7 + 150 * math.sin(t * 0.45)) - 350), glow_p)
        d = ImageDraw.Draw(img)
        for (px, py, pr, spd) in parts:
            yy = (py - t * spd) % H
            d.ellipse((px - pr, yy - pr, px + pr, yy + pr), fill=(120, 150, 230))
        s = state[i]
        bounce = 1 + 0.035 * sm[i] + 0.10 * punch
        shake = (rng.integers(-9, 10), rng.integers(-9, 10)) if t < 0.35 else (0, 0)
        mid = has_mid and T_MID <= t < T_END
        if not mid:
            ch, gl = BIG[s], BIG_GLOW
            k = bounce
            w2, h2 = int(ch.width * k), int(ch.height * k)
            chs = ch.resize((w2, h2), Image.BILINEAR); gls = gl.resize((w2, h2), Image.BILINEAR)
            x = (W - w2) // 2 + shake[0]; y = H - h2 + 40 + int(8 * math.sin(t * 2.4)) + shake[1]
            img.paste(gls, (x, y), gls); img.paste(chs, (x, y), chs)
            if t < T_MID:
                paste_pop(img, hook_imgs[0], W / 2 + shake[0], 160 + shake[1], ease_out_back(t / 0.3))
                paste_pop(img, hook_imgs[1], W / 2 + shake[0], 280 + shake[1], ease_out_back((t - 0.2) / 0.3))
            else:
                e0 = t - T_END
                paste_pop(img, end_imgs[0], W / 2, 160, ease_out_back(e0 / 0.3))
                paste_pop(img, end_imgs[1], W / 2, 280, ease_out_back((e0 - 0.15) / 0.3))
                paste_pop(img, end_imgs[2], W / 2, 400, ease_out_back((e0 - 0.3) / 0.3))
            cap_y = 1440
        else:
            idx = max([k2 for k2, (ct, _) in enumerate(cards) if t >= ct] or [0])
            ct, c = cards[idx]
            ci = card_imgs[idx]
            ch, gl = SMALL[s], SMALL_GLOW
            k = 1 + 0.05 * sm[i]
            w2, h2 = int(ch.width * k), int(ch.height * k)
            chs = ch.resize((w2, h2), Image.BILINEAR); gls = gl.resize((w2, h2), Image.BILINEAR)
            x = W - w2 + 50; y = H - h2 + 30 + int(6 * math.sin(t * 2.4))
            img.paste(gls, (x, y), gls); img.paste(chs, (x, y), chs)
            pr = ease_out_back((t - ct) / 0.4)
            ang = (1 - min(1, (t - ct) / 0.4)) * 7
            cl = ci.rotate(ang, resample=Image.BILINEAR, expand=True) if ang > 0.2 else ci
            cx = int(70 + (1 - pr) * 1100) - (cl.width - ci.width) // 2
            img.paste(cl, (cx, 230 - (cl.height - ci.height) // 2), cl)
            cap_y = 1165
        for a, b, g in chunks:
            if a <= t < b:
                key = " ".join(g)
                if key not in cap_cache:
                    cap_cache[key] = caption_layer(g)
                paste_pop(img, cap_cache[key], W / 2, cap_y, 1.0 + 0.25 * (1 - ease_out((t - a) / 0.12)))
                break
        # progress bar
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 10), fill=(20, 40, 90)); d.rectangle((0, 0, int(W * t / total), 10), fill=YEL)
        # flash on section change
        if s0 > 0 and dt < 0.1:
            a = int(150 * (1 - dt / 0.1))
            img = Image.blend(img, Image.new("RGB", (W, H), WHITE), a / 255)
        p.stdin.write(img.tobytes())
        for name, tt in (("hook", 1.2), ("mid", (T_MID + 1.0) if has_mid else 0), ("end", T_END + 0.8)):
            if name not in stills and t >= tt:
                stills[name] = img.copy()
    p.stdin.close(); p.wait()

    bed = os.path.join(tmp, "bed.wav")
    write_wav(bed, synth_bed(total, hits))
    out_mp4 = os.path.join(outdir, "reel.mp4")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", silent, "-i", vo, "-i", bed,
         "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
         "-movflags", "+faststart", "-shortest", out_mp4])
    for name, im in stills.items():
        im.resize((360, 640)).save(os.path.join(tmp, f"still_{name}.png"))

    # cover
    cv = spec.get("cover", {})
    lines = cv.get("lines") or [spec["hook"][0], "", spec["hook"][1], ""]
    img = bg_base.copy()
    img.paste(glow_y, (W - 650, H - 900), glow_y)
    chc = cut[2].resize((int(cut[2].width * 1060 / cut[2].height), 1060), Image.LANCZOS)
    gl = glow_of(chc)
    img.paste(gl, ((W - chc.width) // 2 + 170, H - chc.height), gl)
    img.paste(chc, ((W - chc.width) // 2 + 170, H - chc.height), chc)
    d = ImageDraw.Draw(img)
    y = 260
    for k2, ln in enumerate(lines):
        if not ln:
            continue
        if k2 == 2:
            f = fit(ln, 84, 940)
            d.rounded_rectangle((60, y - 60, 60 + d.textlength(ln, font=f) + 50, y + 60), 24, fill=YEL)
            d.text((85, y), ln, font=f, fill=BG, anchor="lm"); y += 130
        else:
            f = fit(ln, 150 if k2 < 2 else 110, 940)
            d.text((70, y), ln, font=f, fill=YEL if k2 == 1 else WHITE, stroke_width=8, stroke_fill=(0, 0, 0), anchor="lm")
            y += 160 if k2 < 2 else 130
    x = 70
    for c in cv.get("chips", []):
        fc = F(44, False); w = d.textlength(c, font=fc) + 60
        d.rounded_rectangle((x, y, x + w, y + 76), 38, fill=PURPLE)
        d.text((x + w / 2, y + 38), c, font=fc, fill=WHITE, anchor="mm"); x += w + 22
    img.save(os.path.join(outdir, "cover.jpg"), quality=92)
    print(json.dumps({"reel": out_mp4, "seconds": round(total, 2), "phrases": len(phrases), "segments": len(segs), "stills": tmp}))


if __name__ == "__main__":
    build(*sys.argv[1:4])
