from __future__ import annotations

import base64
import datetime
import io
import os
import re
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from image_quota import FLUX_SCHNELL_NEURONS_PER_IMAGE, reserve_neurons

OUT = Path('data/images')
OUT.mkdir(parents=True, exist_ok=True)
FLUX_MODEL = '@cf/black-forest-labs/flux-1-schnell'
FLUX_STEPS = 4


def make_cover(title, category='Авто'):
    """Legacy local cover kept for backward compatibility/fallback metadata."""
    safe = re.sub(r'[^\w\-а-яА-Я ]+', '', title)[:60].strip().replace(' ', '_') or 'article'
    path = OUT / (datetime.datetime.now().strftime('%Y%m%d_%H%M%S_') + safe + '.jpg')
    img = Image.new('RGB', (1600, 900), '#171a1f')
    d = ImageDraw.Draw(img)
    for x in range(0, 1600, 40):
        d.rectangle((x, 0, x + 20, 900), fill=(24 + x // 20 % 20, 28 + x // 30 % 18, 35 + x // 40 % 20))
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 58)
        small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 30)
    except Exception:
        font = small = None
    d.text((90, 100), category.upper(), font=small, fill='white')
    lines = textwrap.wrap(title, width=34)
    y = 210
    for line in lines[:5]:
        d.text((90, y), line, font=font, fill='white')
        y += 72
    d.rounded_rectangle((90, 760, 430, 825), radius=18, fill=(230, 230, 230))
    d.text((120, 778), 'АВТО БЕЗ ПЕРЕПЛАТЫ', font=small, fill=(20, 20, 20))
    img.save(path, quality=90)
    return path


def editorial_prompts(headline: str, count: int = 5) -> list[str]:
    """Build up to five distinct editorial scenes without another AI call."""
    count = max(1, min(5, int(count)))
    subject = (headline or 'the exact car model discussed in the article').strip()[:220]
    base = (
        f'Photorealistic editorial automotive photography about: {subject}. '
        'The vehicle model and generation must match the named subject accurately, '
        'factory body proportions, realistic wheels, headlights and grille, '
        'natural materials, no invented badges, no readable text, no watermark. '
    )
    scenes = [
        'Hero image, front three-quarter exterior view on a clean urban road, soft natural daylight, 16:9 editorial composition.',
        'Rear three-quarter exterior view on a real road, natural daylight, realistic reflections, documentary automotive magazine style.',
        'Side profile parked near modern architecture, neutral daylight, full vehicle visible, realistic perspective.',
        'Interior cockpit view from the rear seats looking forward, realistic dashboard and steering wheel appropriate to the named vehicle, natural light.',
        'Practical ownership scene at a parking or service area, the named vehicle clearly visible, realistic everyday environment, editorial photojournalism.',
    ]
    return [base + scene for scene in scenes[:count]]


def generate_cloudflare_image(prompt: str, output_path: str | Path, *, quota_reserved: bool = False) -> dict:
    """Generate one 1024x1024 FLUX Schnell JPEG and return measured usage."""
    token = os.getenv('CLOUDFLARE_AI_API_TOKEN', '').strip()
    account = os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip()
    if not token or not account:
        raise RuntimeError('CLOUDFLARE_AI_API_TOKEN/CLOUDFLARE_ACCOUNT_ID не настроены')
    if not quota_reserved and not reserve_neurons(FLUX_SCHNELL_NEURONS_PER_IMAGE):
        raise RuntimeError('Workers AI daily factory neuron budget exhausted')

    url = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{FLUX_MODEL}'
    response = requests.post(
        url,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={'prompt': prompt, 'steps': FLUX_STEPS},
        timeout=180,
    )
    response.raise_for_status()
    payload = response.json()
    image64 = (payload.get('result') or {}).get('image')
    if not image64:
        raise RuntimeError('Cloudflare Workers AI response has no result.image')
    raw = base64.b64decode(image64)
    image = Image.open(io.BytesIO(raw))
    image.load()
    if image.width <= 0 or image.height <= 0:
        raise RuntimeError('Generated image has invalid dimensions')

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if image.mode != 'RGB':
        image = image.convert('RGB')
    image.save(path, format='JPEG', quality=92, optimize=True)

    usage = (payload.get('result') or {}).get('usage') or payload.get('usage') or {}
    measured = float(usage.get('neurons') or response.headers.get('cf-ai-neurons') or FLUX_SCHNELL_NEURONS_PER_IMAGE)
    return {
        'path': str(path),
        'resolution': [image.width, image.height],
        'neurons': measured,
        'model': FLUX_MODEL,
        'steps': FLUX_STEPS,
    }


def make_contact_sheet(images: list[str | Path], output_path: str | Path, headline: str = '') -> Path:
    """Create one Telegram preview image for an approved-size 3-5 candidate set."""
    count = len(images)
    if count < 3 or count > 5:
        raise ValueError(f'Contact sheet requires 3-5 images; got {count}')
    thumbs = []
    for src in images:
        im = Image.open(src).convert('RGB')
        thumbs.append(ImageOps.fit(im, (640, 640), method=Image.Resampling.LANCZOS))

    if count == 3:
        positions = [(0, 100), (640, 100), (1280, 100)]
        height = 780
    elif count == 4:
        positions = [(320, 100), (960, 100), (320, 760), (960, 760)]
        height = 1440
    else:
        positions = [(0, 100), (640, 100), (1280, 100), (320, 760), (960, 760)]
        height = 1440

    sheet = Image.new('RGB', (1920, height), 'white')
    draw = ImageDraw.Draw(sheet)
    try:
        title_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 34)
        number_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 46)
    except Exception:
        title_font = number_font = None

    title = (headline or 'Набор изображений')[:100]
    draw.text((40, 25), title, fill='black', font=title_font)
    for idx, (im, pos) in enumerate(zip(thumbs, positions), 1):
        sheet.paste(im, pos)
        x, y = pos
        draw.ellipse((x + 18, y + 18, x + 86, y + 86), fill='white', outline='black', width=3)
        draw.text((x + 36, y + 24), str(idx), fill='black', font=number_font)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, 'JPEG', quality=88, optimize=True)
    return path
