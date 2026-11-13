#!/usr/bin/env python3
"""AI Bhai - Head Manager QA gate.

Every reel must PASS this before it is scheduled. Exit code 0 = PASS, 1 = FAIL.

    python3 pipeline/qa_check.py reels/<id>/ "<instagram caption text>"

Checks (pass 1, automatic):
  video   : 1080x1920, ~30 fps, H.264, 8-90 s, file < 95 MB, no black/frozen stretches
  audio   : AAC present, not silent, not clipped, voice length matches script
  lipsync : mouth moves on speech, closes in pauses, enough shape changes
  text    : on-screen text Latin only (no Gujarati/Devanagari), fits the screen, cards valid
  CTA     : "bio link" CTA + Follow line in script, no "comment karo" style CTA
  caption : bio-link line, @aibhai_hindi, 3-10 hashtags, < 2200 chars, Latin/emoji only
  cover   : cover.jpg exists, 1080x1920
Pass 2 (human-style): writes contact_sheet.jpg (12 frames) that must be looked at.
Writes qa_report.json next to the reel.
"""
import json, os, re, subprocess, sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "assets", "Poppins-Bold.ttf")
NON_LATIN = re.compile(r"[ऀ-෿]")  # Devanagari, Bengali, Gurmukhi, Gujarati, Tamil, Telugu, Kannada, Malayalam...
BAD_CTA = re.compile(r"comment\s*(karo|kare|kijiye|me|mein|below)|comment\s+['\"]?[A-Z]{2,}|dm\s+karo", re.I)


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path):
    r = sh(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    return json.loads(r.stdout or "{}")


def main(reel_dir, caption):
    res = []  # (level, area, message) level in PASS/WARN/FAIL

    def ok(area, msg): res.append(("PASS", area, msg))
    def warn(area, msg): res.append(("WARN", area, msg))
    def fail(area, msg): res.append(("FAIL", area, msg))

    mp4 = os.path.join(reel_dir, "reel.mp4")
    cover = os.path.join(reel_dir, "cover.jpg")
    spec_p = os.path.join(reel_dir, "spec.json")
    meta_p = os.path.join(reel_dir, "qa_meta.json")
    for p in (mp4, cover, spec_p):
        if not os.path.exists(p):
            fail("files", f"missing {os.path.basename(p)}")
    if any(r[0] == "FAIL" for r in res):
        return finish(reel_dir, res)
    spec = json.load(open(spec_p))

    # ---------- video ----------
    info = probe(mp4)
    v = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), None)
    a = next((s for s in info.get("streams", []) if s["codec_type"] == "audio"), None)
    dur = float(info.get("format", {}).get("duration", 0))
    size_mb = os.path.getsize(mp4) / 1e6
    if not v:
        fail("video", "no video stream")
    else:
        (ok if (v["width"], v["height"]) == (1080, 1920) else fail)("video", f"resolution {v['width']}x{v['height']}")
        num, den = map(int, v["r_frame_rate"].split("/"))
        fps = num / den
        (ok if 29 <= fps <= 31 else fail)("video", f"fps {fps:.2f}")
        (ok if v["codec_name"] == "h264" else fail)("video", f"codec {v['codec_name']}")
        (ok if v.get("pix_fmt") == "yuv420p" else warn)("video", f"pix_fmt {v.get('pix_fmt')}")
    (ok if 8 <= dur <= 90 else fail)("video", f"duration {dur:.1f}s")
    (ok if size_mb < 95 else fail)("video", f"size {size_mb:.1f} MB")

    bd = sh(["ffmpeg", "-hide_banner", "-i", mp4, "-vf", "blackdetect=d=0.5:pix_th=0.08", "-an", "-f", "null", "-"]).stderr
    (fail if "black_start" in bd else ok)("video", "black frames >0.5s" if "black_start" in bd else "no black stretches")
    fz = sh(["ffmpeg", "-hide_banner", "-i", mp4, "-vf", "freezedetect=n=0.001:d=2.5", "-an", "-f", "null", "-"]).stderr
    (fail if "freeze_start" in fz else ok)("video", "frozen video >2.5s" if "freeze_start" in fz else "no frozen stretches")

    # ---------- audio ----------
    if not a:
        fail("audio", "no audio stream")
    else:
        (ok if a["codec_name"] == "aac" else warn)("audio", f"codec {a['codec_name']}")
        vd = sh(["ffmpeg", "-hide_banner", "-i", mp4, "-af", "volumedetect", "-vn", "-f", "null", "-"]).stderr
        mean = float(re.search(r"mean_volume: (-?[\d.]+)", vd).group(1))
        peak = float(re.search(r"max_volume: (-?[\d.]+)", vd).group(1))
        (ok if mean > -32 else fail)("audio", f"mean volume {mean} dB")
        (ok if peak <= -0.1 else warn)("audio", f"peak {peak} dB")
        words = sum(len(p.split()) for p in spec["phrases"])
        wps = words / max(dur, 1)
        (ok if 1.3 <= wps <= 4.5 else fail)("audio", f"speech pace {wps:.2f} words/s (script vs voice match)")

    # ---------- lip-sync ----------
    if not os.path.exists(meta_p):
        fail("lipsync", "qa_meta.json missing - re-render with current make_reel.py")
    else:
        m = json.load(open(meta_p))
        st, vc, fpsm = m["mouth_states"], m["voiced"], m["fps"]
        n_voiced = sum(vc) or 1
        open_on_voice = sum(1 for s, x in zip(st, vc) if x and s > 0) / n_voiced
        changes = sum(1 for i in range(1, len(st)) if st[i] != st[i - 1]) / (len(st) / fpsm)
        silent = [s for s, x in zip(st, vc) if not x]
        closed_on_silence = (sum(1 for s in silent if s == 0) / len(silent)) if silent else 1
        shapes = len(set(st))
        (ok if open_on_voice >= 0.55 else fail)("lipsync", f"mouth open on {open_on_voice:.0%} of speech frames")
        (ok if 3 <= changes <= 14 else fail)("lipsync", f"{changes:.1f} mouth changes/s")
        (ok if closed_on_silence >= 0.9 else fail)("lipsync", f"mouth closed on {closed_on_silence:.0%} of pauses")
        (ok if shapes >= 4 else fail)("lipsync", f"{shapes} mouth shapes used")

    # ---------- on-screen text ----------
    font = lambda s: ImageFont.truetype(FONT, s)
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    texts = list(spec["phrases"]) + spec.get("hook", []) + spec.get("end", [])
    for c in spec.get("cards", []):
        texts += [c.get("title", "")] + c.get("lines", []) + c.get("chips", [])
    cv = spec.get("cover", {})
    texts += cv.get("lines", []) + cv.get("chips", [])
    bad = [t for t in texts if NON_LATIN.search(t)]
    (fail if bad else ok)("text", f"non-Latin script on screen: {bad[:3]}" if bad else "all on-screen text in Roman Hinglish")
    for t in spec.get("hook", []) + spec.get("end", []):
        if d.textlength(t, font=font(50)) > 960:
            fail("text", f"header too long, will be tiny/cut: '{t}'")
    for w in " ".join(spec["phrases"]).split():
        if d.textlength(w, font=font(46)) > 900:
            fail("text", f"word too long for caption: '{w}'")
    for c in spec.get("cards", []):
        if not (0 <= c["at"] < len(spec["phrases"])):
            fail("text", f"card '{c.get('title')}' points to phrase {c['at']} (only {len(spec['phrases'])})")
        for ln in c.get("lines", []):
            if len(ln) > 30:
                warn("text", f"card line long ({len(ln)} chars): '{ln}'")
    ats = [c["at"] for c in spec.get("cards", [])]
    (ok if ats == sorted(ats) else fail)("text", "cards in order")
    for k in ("hook_phrases", "end_phrases"):
        if spec.get(k, 0) > len(spec["phrases"]):
            fail("text", f"{k} larger than phrase count")
    hp, ep = spec.get("hook_phrases", 0), spec.get("end_phrases", 0)
    if ats and (min(ats) < hp or max(ats) >= len(spec["phrases"]) - ep):
        warn("text", "a card overlaps hook/end section")

    # ---------- CTA ----------
    script = " ".join(spec["phrases"])
    (ok if re.search(r"bio\s*link", script, re.I) else fail)("cta", "voice CTA 'bio link'")
    (ok if re.search(r"follow", script, re.I) else fail)("cta", "voice 'Follow' line")
    (fail if BAD_CTA.search(script) else ok)("cta", "no comment/DM CTA in voice (automation not live yet)")

    # ---------- caption ----------
    if caption is not None:
        tags = re.findall(r"#\w+", caption)
        (ok if re.search(r"bio link", caption, re.I) else fail)("caption", "bio-link line")
        (ok if "@aibhai_hindi" in caption else fail)("caption", "@aibhai_hindi mention")
        (ok if 3 <= len(tags) <= 10 else fail)("caption", f"{len(tags)} hashtags")
        (ok if len(tags) == len(set(t.lower() for t in tags)) else fail)("caption", "no duplicate hashtags")
        (ok if len(caption) < 2200 else fail)("caption", f"length {len(caption)}")
        (fail if NON_LATIN.search(caption) else ok)("caption", "Roman script only")
        (fail if BAD_CTA.search(caption) else ok)("caption", "no comment/DM CTA")
        (fail if re.search(r"\{|\}|TODO|lorem|xxx", caption, re.I) else ok)("caption", "no placeholders")
        first = caption.strip().split("\n")[0]
        (ok if 10 <= len(first) <= 125 else warn)("caption", f"first line {len(first)} chars")

    # ---------- cover ----------
    im = Image.open(cover)
    (ok if im.size == (1080, 1920) else fail)("cover", f"cover {im.size[0]}x{im.size[1]}")

    # ---------- pass 2: contact sheet ----------
    sheet = os.path.join(reel_dir, "contact_sheet.jpg")
    times = [dur * (k + 0.5) / 12 for k in range(12)]
    tiles = []
    for t in times:
        fp = os.path.join(reel_dir, "_f.jpg")
        sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", mp4, "-frames:v", "1", "-vf", "scale=270:480", fp])
        if os.path.exists(fp):
            tiles.append(Image.open(fp).copy()); os.remove(fp)
    if tiles:
        cs = Image.new("RGB", (270 * 6, 480 * 2), "black")
        for k, tl in enumerate(tiles):
            cs.paste(tl, ((k % 6) * 270, (k // 6) * 480))
        cs.save(sheet, quality=85)
        ok("review", "contact_sheet.jpg written - LOOK AT IT before scheduling")
    else:
        fail("review", "could not extract frames")

    return finish(reel_dir, res)


def finish(reel_dir, res):
    verdict = "FAIL" if any(r[0] == "FAIL" for r in res) else "PASS"
    rep = {"verdict": verdict, "checks": [{"level": l, "area": a, "msg": m} for l, a, m in res]}
    json.dump(rep, open(os.path.join(reel_dir, "qa_report.json"), "w"), indent=1, ensure_ascii=False)
    for l, a, m in res:
        if l != "PASS":
            print(f"{l:4} [{a}] {m}")
    print(f"QA {verdict}: {sum(r[0]=='PASS' for r in res)} pass, {sum(r[0]=='WARN' for r in res)} warn, {sum(r[0]=='FAIL' for r in res)} fail")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    cap = sys.argv[2] if len(sys.argv) > 2 else None
    if cap and os.path.isfile(cap):
        cap = open(cap).read()
    sys.exit(main(sys.argv[1], cap))
