"""Builds guide/AI-Bhai-10-AI-Tools.pdf (phone-friendly 9:16 pages)."""
import os
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader, simpleSplit

HERE = os.path.dirname(os.path.abspath(__file__))
FD = "/usr/share/fonts/truetype/google-fonts/"
pdfmetrics.registerFont(TTFont("PB", FD + "Poppins-Bold.ttf"))
pdfmetrics.registerFont(TTFont("PM", FD + "Poppins-Medium.ttf"))
pdfmetrics.registerFont(TTFont("PR", FD + "Poppins-Regular.ttf"))

W, H = 540, 960
NAVY = (3 / 255, 20 / 255, 63 / 255)
CARD = (15 / 255, 32 / 255, 82 / 255)
YEL = (250 / 255, 204 / 255, 21 / 255)
PUR = (124 / 255, 58 / 255, 237 / 255)
WHITE = (1, 1, 1)
GREY = (0.78, 0.82, 0.9)
CHAR = os.path.join(HERE, "..", "pipeline", "assets", "frame_C.png")

TOOLS = [
    ("ChatGPT", "Likhne ka dost", "Email, caption, ideas, report – sab likhwao. Sawaal poocho, simple Hindi me samjho.",
     "Tum ek expert marketer ho. Meri chai ki dukaan ke liye 5 Instagram captions likho, Hinglish me."),
    ("Claude", "Lambi files ka master", "PDF ya lamba text daalo aur summary, points ya naya draft maango. Likhne aur sochne me bahut accha.",
     "Is PDF ke 5 main points simple Hindi me batao, aur mere kaam ki 3 cheezein alag se."),
    ("Gemini", "Google wala AI", "Google ke apps ke saath kaam karta hai. YouTube video ka link do aur main points poocho.",
     "Is YouTube video ke main points batao aur mere liye 3 action steps likho."),
    ("Perplexity", "Google ka smart bhai", "Seedha jawaab deta hai, saath me source link bhi. Research aur news ke liye best.",
     "India me 2026 me sabse zyada demand wali 5 skills kaunsi hain? Sources ke saath batao."),
    ("NotebookLM", "Padhai ka teacher", "Apni notes ya PDF upload karo. Samjho, MCQ banwao, aur Audio Overview se podcast ki tarah suno.",
     "Ye chapter simple Hindi me samjhao aur 10 MCQ banao, answers ke saath."),
    ("Canva", "Design 2 minute me", "Poster, post, resume, thumbnail – template chuno, AI se text aur design banwao.",
     "Diwali offer poster: 20% off, chai aur snacks, bright colours."),
    ("Gamma", "PPT apne aap", "Topic likho, AI poori presentation bana deta hai. Theme chuno aur PPT ya PDF download karo.",
     "Digital Marketing basics par 8 slides ki presentation, students ke liye."),
    ("Napkin AI", "Text se diagram", "Apna paragraph paste karo, ye usse flowchart ya diagram bana deta hai. Notes aur PPT ke liye mast.",
     "(Apne notes ka koi bhi paragraph paste karo aur 'Generate' dabao.)"),
    ("CapCut", "Auto captions", "Video daalo, Text > Auto captions dabao. Hindi ya English captions apne aap aa jaate hain.",
     "(Reels ke liye: captions + yellow highlight = zyada log poori video dekhte hain.)"),
    ("Photoroom", "Product photo studio", "Phone ki photo se background hatao aur safed ya naya background lagao. remove.bg bhi yahi karta hai.",
     "(Meesho, Amazon, Instagram shop ke liye product photos 1 click me.)"),
]


def bg(c):
    c.setFillColorRGB(*NAVY); c.rect(0, 0, W, H, fill=1, stroke=0)


def text(c, x, y, s, font="PR", size=16, color=WHITE, maxw=W - 80, lead=1.35):
    c.setFillColorRGB(*color); c.setFont(font, size)
    lines = simpleSplit(s, font, size, maxw)
    for ln in lines:
        c.drawString(x, y, ln); y -= size * lead
    return y


def footer(c, n):
    c.setFillColorRGB(*GREY); c.setFont("PM", 11)
    c.drawString(40, 30, "AI Bhai  |  @aibhai_hindi")
    c.drawRightString(W - 40, 30, str(n))


def chip(c, x, y, s, color=PUR, tcolor=WHITE, size=12):
    w = pdfmetrics.stringWidth(s, "PM", size) + 24
    c.setFillColorRGB(*color); c.roundRect(x, y, w, size + 14, (size + 14) / 2, fill=1, stroke=0)
    c.setFillColorRGB(*tcolor); c.setFont("PM", size); c.drawString(x + 12, y + 8, s)
    return w


def build(out):
    c = canvas.Canvas(out, pagesize=(W, H))
    c.setTitle("10 AI Tools Jo Har Kisi Ko Pata Hone Chahiye – AI Bhai")
    c.setAuthor("AI Bhai (@aibhai_hindi)")

    # cover
    bg(c)
    c.drawImage(ImageReader(CHAR), 150, 0, width=420, height=630, mask="auto")
    text(c, 40, H - 110, "FREE GUIDE", "PB", 18, YEL)
    y = text(c, 40, H - 175, "10 AI Tools", "PB", 54, WHITE)
    y = text(c, 40, y + 10, "Jo Har Kisi Ko", "PB", 38, WHITE)
    c.setFillColorRGB(*YEL); c.roundRect(34, y - 16, 420, 56, 14, fill=1, stroke=0)
    text(c, 48, y, "Pata Hone Chahiye", "PB", 34, NAVY)
    x = 40
    for s in ["Free", "Hindi", "Ready Prompts"]:
        x += chip(c, x, y - 70, s) + 10
    footer(c, 1); c.showPage()

    # how to use
    bg(c)
    y = text(c, 40, H - 110, "Bhai log, namaste!", "PB", 30, YEL)
    y = text(c, 40, y - 10, "Main AI Bhai hoon – ek AI, jo tumhe AI sikhata hai. Is guide me wahi 10 tools hain jo maine sabse kaam ke paaye.", "PR", 17, WHITE)
    y -= 20
    for t in ["Har tool ka kaam ek line me", "Kis ke liye best hai", "Ek ready prompt – copy karo, paste karo, kaam khatam",
              "Shuruaat free version se ho jaati hai (plans badalte rehte hain)"]:
        c.setFillColorRGB(*YEL); c.circle(52, y + 6, 5, fill=1, stroke=0)
        y = text(c, 70, y, t, "PM", 16, WHITE, maxw=W - 110) - 8
    y -= 20
    c.setFillColorRGB(*CARD); c.roundRect(34, y - 150, W - 68, 170, 18, fill=1, stroke=0)
    yy = text(c, 54, y - 10, "Golden rule", "PB", 18, YEL)
    text(c, 54, yy - 4, "AI ka jawaab seedha copy-paste mat karo. Number, date aur naam ek baar khud check karo – AI bhi galti karta hai. Main bhi!", "PR", 15, WHITE, maxw=W - 110)
    footer(c, 2); c.showPage()

    # tools, 2 per page
    n = 3
    for i in range(0, len(TOOLS), 2):
        bg(c)
        y0 = H - 90
        for j, (name, tag, desc, prompt) in enumerate(TOOLS[i:i + 2]):
            num = i + j + 1
            dl = len(simpleSplit(desc, "PR", 16, W - 110)); pl = len(simpleSplit(prompt, "PM", 14, W - 140))
            bottom = y0 - 125 - dl * 21.6 - 14 - 24 - (pl * 19 + 40) - 20
            c.setFillColorRGB(*CARD); c.roundRect(30, bottom, W - 60, y0 - bottom, 22, fill=1, stroke=0)
            c.setFillColorRGB(*YEL); c.circle(80, y0 - 50, 28, fill=1, stroke=0)
            c.setFillColorRGB(*NAVY); c.setFont("PB", 26); c.drawCentredString(80, y0 - 60, str(num))
            text(c, 125, y0 - 48, name, "PB", 28, WHITE, maxw=360)
            text(c, 125, y0 - 74, tag, "PM", 14, YEL, maxw=360)
            yy = text(c, 54, y0 - 125, desc, "PR", 16, WHITE, maxw=W - 110)
            yy -= 14
            text(c, 54, yy, "Try karo:", "PB", 14, YEL)
            bh = pl * 19 + 40
            c.setFillColorRGB(*NAVY); c.roundRect(48, yy - 24 - bh, W - 96, bh, 14, fill=1, stroke=0)
            text(c, 64, yy - 24 - 26, prompt, "PM", 14, GREY, maxw=W - 140)
            y0 = bottom - 40
        footer(c, n); n += 1; c.showPage()

    # prompt formula
    bg(c)
    y = text(c, 40, H - 110, "Bonus 1", "PB", 18, YEL)
    y = text(c, 40, y - 4, "Prompt ka 4-step formula", "PB", 32, WHITE)
    y = text(c, 40, y - 6, "Isse kisi bhi AI ka jawaab 10 guna better ho jaata hai.", "PR", 16, GREY)
    y -= 20
    for k, (h, d) in enumerate([("Role", "Tum ek expert ___ ho"), ("Kaam", "Mujhe kya chahiye, saaf likho"),
                                ("Context", "Kiske liye, kitna lamba, kis tone me"), ("Format", "5 points me / table me / 100 words me")]):
        c.setFillColorRGB(*CARD); c.roundRect(34, y - 70, W - 68, 86, 16, fill=1, stroke=0)
        c.setFillColorRGB(*YEL); c.circle(72, y - 27, 20, fill=1, stroke=0)
        c.setFillColorRGB(*NAVY); c.setFont("PB", 20); c.drawCentredString(72, y - 34, str(k + 1))
        text(c, 106, y - 18, h, "PB", 20, WHITE)
        text(c, 106, y - 44, d, "PR", 15, GREY, maxw=W - 160)
        y -= 104
    y -= 6
    text(c, 40, y, "Example:", "PB", 15, YEL)
    text(c, 40, y - 26, "\"Tum ek HR expert ho. Mera ye resume marketing job ke liye improve karo. Fresher hoon. Har point result ke saath, 1 page me.\"", "PM", 14, WHITE)
    footer(c, n); n += 1; c.showPage()

    # safety
    bg(c)
    y = text(c, 40, H - 110, "Bonus 2", "PB", 18, YEL)
    y = text(c, 40, y - 4, "Ye cheezein AI ko kabhi mat batana", "PB", 30, WHITE)
    y -= 24
    for h, d in [("Aadhaar, PAN, bank details", "Koi bhi ID ya account number nahi."), ("Password aur OTP", "Kisi ko bhi nahi – AI ko bhi nahi."),
                 ("Company ka secret data", "Naam aur number hata ke sawaal poocho.")]:
        c.setFillColorRGB(*CARD); c.roundRect(34, y - 80, W - 68, 96, 16, fill=1, stroke=0)
        text(c, 56, y - 20, h, "PB", 19, YEL, maxw=W - 110)
        text(c, 56, y - 50, d, "PR", 15, WHITE, maxw=W - 110)
        y -= 116
    y -= 10
    c.setFillColorRGB(*CARD); c.roundRect(34, y - 150, W - 68, 166, 16, fill=1, stroke=0)
    yy = text(c, 56, y - 20, "AI voice scam se bacho", "PB", 19, YEL)
    text(c, 56, yy - 4, "AI kisi ki bhi awaaz copy kar sakta hai. Family se paise maangne wali call aaye to phone kaato aur khud wapas call karo. Ghar me ek secret code word rakho.", "PR", 15, WHITE, maxw=W - 110)
    footer(c, n); n += 1; c.showPage()

    # closing
    bg(c)
    c.drawImage(ImageReader(CHAR), 150, 0, width=373, height=560, mask="auto")
    y = text(c, 40, H - 120, "Chai khatam,", "PB", 40, WHITE)
    y = text(c, 40, y + 6, "hack khatam!", "PB", 40, YEL)
    y = text(c, 40, y - 10, "Roz 1 naya AI hack ke liye follow karo:", "PM", 17, WHITE)
    c.setFillColorRGB(*YEL); c.roundRect(34, y - 40, 300, 54, 14, fill=1, stroke=0)
    text(c, 50, y - 22, "@aibhai_hindi", "PB", 26, NAVY)
    text(c, 40, y - 80, "Guide pasand aayi? Kisi dost ko bhejo.", "PR", 15, GREY)
    footer(c, n); c.showPage()
    c.save()


if __name__ == "__main__":
    build(os.path.join(HERE, "AI-Bhai-10-AI-Tools.pdf"))
