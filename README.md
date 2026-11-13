# AI Bhai media

Public media and the reel pipeline for Instagram @aibhai_hindi.

- `reels/<id>/` – reel.mp4, cover.jpg, vo.mp3 (voiceover), spec.json
- `content/queue.json` – upcoming reel scripts and their status
- `pipeline/make_reel.py` – turns spec.json + vo.mp3 into a lip-synced reel and cover


## Head Manager QA gate (mandatory)
No reel is scheduled unless it passes BOTH checks:
1. `python3 pipeline/qa_check.py reels/<id>/ "<caption>"` must print `QA PASS` (video, audio, lip-sync, on-screen text, CTA, caption, cover). It writes `qa_report.json` and `contact_sheet.jpg`.
2. Open `contact_sheet.jpg` and look at it: text inside the screen, nothing cut, cards readable, character present, end screen says "Free Guide: Bio Link".
On FAIL: fix the script/caption, re-voice or re-render, and run again. After scheduling, read the post back from Metricool and confirm time, type, caption and AI label.
