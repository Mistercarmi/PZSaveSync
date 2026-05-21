"""Génère l'image sociale (1280x640) du repo pour les previews Discord/Twitter."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "social_preview.png"

# Couleurs alignées avec la palette de l'app
BG = (21, 23, 27)           # #15171b
BG_GRADIENT = (35, 38, 46)  # #23262e
ACCENT_GREEN = (46, 139, 87)   # #2e8b57
ACCENT_BLUE = (44, 127, 184)   # #2c7fb8
ACCENT_GOLD = (245, 200, 66)   # #f5c842
TEXT = (230, 232, 236)
TEXT_MUTED = (138, 142, 151)
TEXT_DIM = (90, 94, 102)


def _font(size: int, bold: bool = False, emoji: bool = False) -> ImageFont.FreeTypeFont:
    """Tente plusieurs polices systèmes, fallback sur la police par défaut."""
    if emoji:
        # Segoe UI Emoji (Windows) ou Apple Color Emoji (macOS)
        for n in ["seguiemj.ttf", "AppleColorEmoji.ttc", "NotoColorEmoji.ttf"]:
            try:
                return ImageFont.truetype(n, size)
            except (OSError, IOError):
                continue
    candidates_bold = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
    candidates_regular = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
    names = candidates_bold if bold else candidates_regular
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def main():
    W, H = 1280, 640
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Dégradé subtil bg → bg_gradient en diagonal
    for y in range(H):
        # Mix factor 0..1
        t = y / H
        r = int(BG[0] + (BG_GRADIENT[0] - BG[0]) * t * 0.4)
        g = int(BG[1] + (BG_GRADIENT[1] - BG[1]) * t * 0.4)
        b = int(BG[2] + (BG_GRADIENT[2] - BG[2]) * t * 0.4)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Coin haut gauche : un "PZ" stylisé en doré (faux logo)
    draw.rounded_rectangle(
        (60, 60, 200, 200), radius=20,
        fill=BG_GRADIENT, outline=ACCENT_GOLD, width=3,
    )
    f_logo = _font(72, bold=True)
    text = "PZ"
    bbox = draw.textbbox((0, 0), text, font=f_logo)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        (60 + (140 - tw) / 2 - bbox[0], 60 + (140 - th) / 2 - bbox[1]),
        text, font=f_logo, fill=ACCENT_GOLD,
    )

    # Titre
    f_title = _font(90, bold=True)
    draw.text((230, 70), "PZ SaveSync", font=f_title, fill=TEXT)

    # Sous-titre
    f_sub = _font(30)
    draw.text(
        (230, 175),
        "Co-op save sharing for Project Zomboid",
        font=f_sub, fill=TEXT_MUTED,
    )

    # Tagline centrale (le pitch en 1 ligne)
    f_pitch = _font(40, bold=True)
    pitch = "Partage tes saves PZ entre potes via Dropbox/Drive/OneDrive"
    bbox = draw.textbbox((0, 0), pitch, font=f_pitch)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2, 280), pitch, font=f_pitch, fill=TEXT)

    f_pitch_sub = _font(26)
    sub = "sans serveur dédié · sans abonnement · open-source"
    bbox = draw.textbbox((0, 0), sub, font=f_pitch_sub)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2, 350), sub, font=f_pitch_sub, fill=TEXT_MUTED)

    # 3 cards en bas pour les features (initiales monospaced pour compat polices)
    cards = [
        ("C", "Cloud", "Push/Pull versionné", ACCENT_BLUE),
        ("L", "Anti-conflit", "Verrou de tour", ACCENT_GOLD),
        ("B", "Bundle", "Save + persos + mods", ACCENT_GREEN),
    ]
    card_w = 320
    card_h = 140
    gap = 30
    total_w = card_w * 3 + gap * 2
    x_start = (W - total_w) // 2
    y_card = 440

    f_icon = _font(64, bold=True)
    f_card_title = _font(24, bold=True)
    f_card_sub = _font(18)
    for i, (icon, title, sub_text, color) in enumerate(cards):
        x = x_start + i * (card_w + gap)
        draw.rounded_rectangle(
            (x, y_card, x + card_w, y_card + card_h),
            radius=12, fill=BG_GRADIENT,
            outline=color, width=2,
        )
        # Cercle de fond pour l'icône
        draw.ellipse(
            (x + 18, y_card + 32, x + 18 + 76, y_card + 32 + 76),
            fill=BG, outline=color, width=2,
        )
        bbox = draw.textbbox((0, 0), icon, font=f_icon)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (x + 18 + (76 - tw) / 2 - bbox[0], y_card + 32 + (76 - th) / 2 - bbox[1]),
            icon, font=f_icon, fill=color,
        )
        draw.text((x + 115, y_card + 40), title, font=f_card_title, fill=TEXT)
        draw.text((x + 115, y_card + 78), sub_text, font=f_card_sub, fill=TEXT_MUTED)

    # Footer URL
    f_url = _font(18)
    url = "github.com/Mistercarmi/PZSaveSync"
    bbox = draw.textbbox((0, 0), url, font=f_url)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2, H - 35), url, font=f_url, fill=TEXT_DIM)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"[done] {OUT}  ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
