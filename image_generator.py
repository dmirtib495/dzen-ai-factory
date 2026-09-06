from __future__ import annotations

import base64
import datetime
import io
import json
import logging
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

log = logging.getLogger(__name__)


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


def _vehicle_mentions(text: str) -> list[str]:
    """Extract repeatedly named make/model subjects without semantic guesswork."""
    brands = (
        "Toyota|Honda|Nissan|Mazda|Mitsubishi|Subaru|Suzuki|Lexus|Infiniti|Acura|"
        "Hyundai|Kia|Genesis|Ford|Chevrolet|Cadillac|Jeep|Tesla|Volkswagen|Audi|"
        "BMW|Mercedes(?:-Benz)?|Porsche|Volvo|Skoda|Renault|Peugeot|Citroen|Fiat|"
        "Land Rover|Range Rover|Geely|Chery|Haval|Exeed|Changan|Li Auto|Zeekr|BYD|Xiaomi|"
        "Lada|УАЗ|ГАЗ"
    )
    pattern = re.compile(
        rf"\b({brands})\s+([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9-]*"
        rf"(?:\s+[A-Za-z0-9][A-Za-z0-9-]*){{0,2}})",
        re.I,
    )
    stop = {
        "с", "и", "или", "против", "для", "при", "на", "в", "от", "до",
        "уже", "может", "был", "будет", "после", "перед",
    }
    counts: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for match in pattern.finditer(text or ""):
        make = match.group(1).strip()
        model_parts = match.group(2).strip().split()
        while model_parts and model_parts[-1].lower() in stop:
            model_parts.pop()
        if not model_parts:
            continue
        subject = f"{make} {' '.join(model_parts)}".strip(" ,.-")
        key = subject.lower()
        counts[key] = counts.get(key, 0) + 1
        canonical.setdefault(key, subject)
    return [
        canonical[key] for key in sorted(
            counts, key=lambda value: (-counts[value], (text or "").lower().find(value))
        )
    ]


def _article_sections(article_markdown: str) -> list[dict]:
    """Return numbered article sections so every visual can cite its editorial source."""
    matches = list(re.finditer(r"^##\\s+(.+?)\\s*$", article_markdown or "", re.M))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(article_markdown or "")
        body = (article_markdown or "")[match.end():end].strip()
        sections.append({
            "index": index + 1,
            "heading": match.group(1).strip(),
            "body": body[:1800],
        })
    return sections


def _extract_json_object(text: str):
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\\s*|\\s*```$", "", raw, flags=re.I | re.S)
    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"\\{.*\\}", raw, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _yandex_visual_plan(
    headline: str,
    article_markdown: str,
    *,
    count: int,
    subject: str,
    comparison_subjects: list[str],
) -> list[dict] | None:
    """Ask one visual editor call to map images to actual article sections."""
    api_key = os.getenv("YANDEX_API_KEY", "").strip()
    folder_id = os.getenv("YANDEX_FOLDER_ID", "").strip()
    model = os.getenv("YANDEX_MODEL", "yandexgpt/latest").strip() or "yandexgpt/latest"
    if not api_key or not folder_id or "placeholder" in api_key.lower() or "placeholder" in folder_id.lower():
        return None

    sections = _article_sections(article_markdown)
    if not sections:
        return None
    comparison_rule = (
        f"The set compares {comparison_subjects[0]} and {comparison_subjects[1]}. "
        "Scene one must show both equally; include one individual scene for each; "
        "at least three scenes must show both as clearly separate vehicles."
        if len(comparison_subjects) >= 2 else
        f"Every scene must show the exact same {subject}, with identical generation, body, paint and wheels."
    )
    prompt = f"""You are the visual editor of an automotive publication.
Create exactly {count} distinct English photo prompts for the supplied Russian article.

ARTICLE HEADLINE:
{headline}

FIXED VISUAL SUBJECT:
{subject}

ARTICLE SECTIONS:
{json.dumps(sections, ensure_ascii=False)}

RULES:
- Every scene must illustrate a concrete situation from one listed section, not a generic car portrait.
- Use different section_index values whenever the article has enough sections.
- The action, location, season and ownership task must agree with that section's text.
- {comparison_rule}
- Do not add another make/model, accident, failure, weather extreme or technical operation absent from the article.
- Photorealistic editorial automotive photo, natural light, plausible Russian environment where relevant.
- No readable text, logos, watermark, invented badges, collage, split screen or fantasy elements.
- Keep the complete vehicle visible unless the chosen section specifically requires a detail inspection.

Return only JSON:
{{"scenes":[{{"section_index":1,"prompt":"English visual description"}}]}}

ARTICLE:
{(article_markdown or "")[:14000]}"""
    try:
        response = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"},
            json={
                "modelUri": f"gpt://{folder_id}/{model}",
                "completionOptions": {"stream": False, "temperature": 0.08, "maxTokens": 3500},
                "messages": [
                    {"role": "system", "text": "You are a strict automotive visual editor. Return valid JSON only."},
                    {"role": "user", "text": prompt},
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        parsed = _extract_json_object(response.json()["result"]["alternatives"][0]["message"]["text"])
        scenes = parsed.get("scenes") if isinstance(parsed, dict) else None
        if not isinstance(scenes, list) or len(scenes) != count:
            raise ValueError("visual planner returned wrong scene count")

        valid = []
        section_ids = set()
        for item in scenes:
            if not isinstance(item, dict):
                raise ValueError("visual planner scene is not an object")
            section_index = int(item.get("section_index", 0))
            scene_prompt = str(item.get("prompt", "")).strip()
            if not (1 <= section_index <= len(sections)) or len(scene_prompt) < 80:
                raise ValueError("visual planner returned invalid section or short prompt")
            valid.append({
                "section_index": section_index,
                "section_heading": sections[section_index - 1]["heading"],
                "prompt": scene_prompt,
            })
            section_ids.add(section_index)
        if len(section_ids) < min(count, len(sections)):
            raise ValueError("visual planner repeated sections despite available article material")

        joined = "\n".join(item["prompt"].lower() for item in valid)
        if len(comparison_subjects) >= 2:
            first, second = comparison_subjects[:2]
            both = sum(first.lower() in item["prompt"].lower() and second.lower() in item["prompt"].lower() for item in valid)
            if first.lower() not in joined or second.lower() not in joined or both < min(3, count):
                raise ValueError("visual comparison plan does not balance both vehicles")
        log.info("YANDEX_VISUAL_PLAN_OK scenes=%s sections=%s subject=%s", count, sorted(section_ids), subject)
        return valid
    except Exception as exc:
        log.warning("YANDEX_VISUAL_PLAN_FALLBACK reason=%s", exc)
        return None


def _render_visual_plan(
    plan: list[dict] | None,
    *,
    rules: str,
    subject: str,
    comparison_subjects: list[str],
) -> list[str] | None:
    if not plan:
        return None
    continuity = (
        f"Keep these two exact vehicles visually consistent and separate throughout the set: "
        f"{comparison_subjects[0]} and {comparison_subjects[1]}. "
        if len(comparison_subjects) >= 2 else
        f"Main subject in every frame: the exact same {subject}. Keep identical generation, body shape, "
        "paint color and wheel design throughout the complete set. "
    )
    prompts = []
    for item in plan:
        scene = item["prompt"]
        if len(comparison_subjects) < 2 and subject.lower() not in scene.lower():
            scene = f"{subject}. {scene}"
        prompts.append(
            rules + continuity +
            f"Editorial source section: {item['section_heading']}. " + scene
        )
    return prompts


def editorial_prompts(
    headline: str,
    count: int = 5,
    *,
    article_markdown: str = "",
    category: str = "",
) -> list[str]:
    """Build five subject-aware editorial scenes without another AI call."""
    count = max(1, min(5, int(count)))
    context = f"{headline}\n{article_markdown}"
    subjects = _vehicle_mentions(context)
    comparison_words = re.search(
        r"\b(сравнен|сравнива|против|versus|\bvs\b|что выбрать|или)\b",
        context,
        re.I,
    )
    is_comparison = len(subjects) >= 2 and (
        bool(comparison_words) or str(category or "").strip().lower() == "сравнения"
    )

    rules = (
        "Photorealistic editorial automotive photography, accurate factory body proportions, "
        "realistic wheels, headlights and grille, natural materials and daylight, 16:9 composition. "
        "No readable text, signs, maps, logos, watermark, invented badges, distorted parts or fantasy elements. "
    )
    if is_comparison:
        first, second = subjects[:2]
        planned = _render_visual_plan(
            _yandex_visual_plan(
                headline,
                article_markdown,
                count=count,
                subject=f"{first} and {second}",
                comparison_subjects=[first, second],
            ),
            rules=rules,
            subject=f"{first} and {second}",
            comparison_subjects=[first, second],
        )
        if planned:
            return planned
        prompts = [
            rules + (
                f"Honest comparison cover: two clearly separate real vehicles, {first} on the left and "
                f"{second} on the right, both fully visible at equal visual importance, parked side by side "
                "on neutral pavement. Do not merge their designs and do not duplicate either model."
            ),
            rules + (
                f"Vehicle one of the comparison only: {first}, front three-quarter exterior view, full car visible. "
                f"No {second} in this frame; preserve the authentic design of {first}."
            ),
            rules + (
                f"Vehicle two of the comparison only: {second}, front three-quarter exterior view, full car visible. "
                f"No {first} in this frame; preserve the authentic design of {second}."
            ),
            rules + (
                f"Direct side-profile comparison: {first} and {second} as two distinct vehicles parked parallel, "
                "both complete and unobstructed, consistent camera distance and scale. No hybridized vehicle."
            ),
            rules + (
                f"Practical buyer inspection scene with both distinct cars, {first} and {second}, in a clean service "
                "or parking area, one mechanic comparing them, both vehicles clearly identifiable and fully separate."
            ),
        ]
        return prompts[:count]

    is_electric_vehicle_topic = bool(re.search(
        r"электромобил|электрокар|зарядн(?:ая|ые|ой|ую|ых)|electric vehicle|\\bev\\b",
        context,
        re.I,
    ))
    if subjects:
        subject = subjects[0]
    elif is_electric_vehicle_topic:
        subject = "pearl white Tesla Model 3, current production body"
    else:
        subject = (headline or "the exact car model discussed in the article").strip()[:220]

    continuity = (
        f"Main subject in every frame: the exact same {subject}. Keep identical body shape, paint color, "
        "wheel design and generation throughout the complete set. The vehicle must remain clearly visible. "
    )
    planned = _render_visual_plan(
        _yandex_visual_plan(
            headline,
            article_markdown,
            count=count,
            subject=subject,
            comparison_subjects=[],
        ),
        rules=rules,
        subject=subject,
        comparison_subjects=[],
    )
    if planned:
        return planned
    if is_electric_vehicle_topic:
        scenes = [
            "Moscow ownership scene: front three-quarter view beside a public curbside charging station, recognizable modern Moscow streetscape, mild daylight.",
            "Winter operation scene: the same car parked outdoors in a snowy Moscow residential area, light frost, realistic cold weather, no dramatic blizzard.",
            "Highway charging scene: the same car at a clean intercity motorway charging stop during a long trip, charging cable connected, practical documentary angle.",
            "Seaside road-trip scene: the same car at a safe coastal rest stop near the Black Sea, luggage visible through an open trunk, natural summer daylight.",
            "Used-car inspection scene: the same car in a clean service bay, owner and technician checking charging port, tires and underbody, editorial photojournalism.",
        ]
    else:
        scenes = [
            "Hero image, front three-quarter exterior view on a clean urban road, soft natural daylight.",
            "Rear three-quarter exterior view on a real road, natural daylight, realistic reflections.",
            "Side profile parked near modern architecture, neutral daylight, full vehicle visible.",
            "Interior cockpit view from the rear seats looking forward, realistic dashboard and steering wheel.",
            "Practical ownership scene at a parking or service area, vehicle clearly visible, editorial photojournalism.",
        ]
    return [rules + continuity + scene for scene in scenes[:count]]

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
