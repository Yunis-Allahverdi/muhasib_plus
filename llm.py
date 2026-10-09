# HesabAI - LLM wrapper
# Provider is picked from whichever key is set (first match wins):
#   GEMINI_API_KEY (Google, free tier)  ->  ANTHROPIC_API_KEY  ->  OPENAI_API_KEY
# Every answer is cached in llm_cache.json, so the evaluation is reproducible
# and the demo does not depend on the network.

import hashlib
import json
import os
import re
import time


# Optional: keys can live in a file called .env next to this file, e.g.
#   GEMINI_API_KEY=your-key
# (.env is in .gitignore - never upload it to GitHub)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8-sig") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# cache lives next to this file, so it is found whatever folder the app is started from
CACHE_FILE = os.environ.get("HESAB_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_cache.json"))
ANTHROPIC_MODEL = os.environ.get("HESAB_CLAUDE_MODEL") or "claude-sonnet-5-5"
# OpenAI-compatible services (Groq, OpenRouter, ...) are used by setting OPENAI_BASE_URL next to OPENAI_API_KEY
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip()
OPENAI_MODEL = os.environ.get("HESAB_OPENAI_MODEL") or ("" if OPENAI_BASE_URL else "gpt-4.1-mini")  # "" = auto-pick
GEMINI_MODEL = os.environ.get("HESAB_GEMINI_MODEL", "")  # empty = pick automatically

# Gemini models tried in this order when HESAB_GEMINI_MODEL is not set
GEMINI_PREFERRED = ["gemini-3.8-flash", "gemini-flash-latest"]
# OpenAI-compatible models tried in this order when HESAB_OPENAI_MODEL is empty (first one the service offers wins)
COMPAT_PREFERRED = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct",
                    "qwen/qwen3-32b", "llama-3.1-8b-instant"]

# USD per 1M tokens (input, output). Free tiers cost 0.
PRICES = {"gemini": (0.0, 0.0), "anthropic": (2.0, 10.0), "openai": (0.4, 1.6),  # anthropic = claude-sonnet-5-5
          "groq": (0.0, 0.0), "openai-compatible": (0.0, 0.0)}

# Quota protection: hard limit on real (non-cached) AI requests per process. 0 = no limit.
MAX_CALLS = int(os.environ.get("HESAB_MAX_LLM_CALLS") or 100)

stats = {"calls": 0, "cached": 0, "in_tokens": 0, "out_tokens": 0, "retries": 0}
_gemini = {"client": None, "model": None}
_compat = {"model": None}

try:
    with open(CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)
except FileNotFoundError:
    cache = {}


def provider():
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        if not OPENAI_BASE_URL:
            return "openai"
        return "groq" if "groq.com" in OPENAI_BASE_URL else "openai-compatible"
    return None


def openai_client():
    from openai import OpenAI
    # max_retries: the SDK waits for the service's retry-after on 429/5xx (free tiers rate-limit per minute)
    return OpenAI(base_url=OPENAI_BASE_URL or None, max_retries=6)


def compat_model():
    # pick a capable chat model from the service's own list, so no model name has to be typed
    if OPENAI_MODEL:
        return OPENAI_MODEL
    if not _compat["model"]:
        ids = [m.id for m in openai_client().models.list().data]
        pick = next((m for m in COMPAT_PREFERRED if m in ids), None)
        if not pick:
            skip = ("whisper", "tts", "guard", "embed", "audio", "playai", "compound", "vision")
            pick = next((m for m in sorted(ids) if not any(s in m for s in skip)), None)
        if not pick:
            raise RuntimeError(f"No chat model found at {OPENAI_BASE_URL}; set HESAB_OPENAI_MODEL in .env")
        _compat["model"] = pick
    return _compat["model"]


def gemini_client():
    if _gemini["client"] is None:
        from google import genai
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        _gemini["client"] = genai.Client(api_key=key)
    return _gemini["client"]


def gemini_model():
    if _gemini["model"]:
        return _gemini["model"]
    if GEMINI_MODEL:
        _gemini["model"] = GEMINI_MODEL
        return GEMINI_MODEL
    names = []
    for m in gemini_client().models.list():
        acts = m.supported_actions or []
        if "generateContent" in acts:
            names.append(m.name.replace("models/", ""))
    for want in GEMINI_PREFERRED:
        if want in names:
            _gemini["model"] = want
            return want
    flash = flash_models(names)
    if not flash:
        raise RuntimeError(f"No Gemini flash model available for this key. Models: {names[:15]}")
    _gemini["model"] = flash[0]
    return flash[0]


def flash_models(names):
    # newest version first, non-lite before lite, no image/audio/live variants
    flash = [n for n in names if "flash" in n and not any(x in n for x in ["image", "tts", "live", "audio", "embedding"])]

    def version(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return (float(m.group(1)) if m else 0, "lite" not in n, "preview" not in n and "exp" not in n)
    return sorted(flash, key=version, reverse=True)


_tried = set()


def switch_model_after_404(msg):
    # Google says which model to use instead ("... use models/gemini-X-flash ..."); otherwise try the next newest
    _tried.add(_gemini["model"])
    m = re.search(r"use models/([\w.\-]+)", msg)
    if m and m.group(1) not in _tried:
        _gemini["model"] = m.group(1)
        return True
    names = [x.name.replace("models/", "") for x in gemini_client().models.list()
             if "generateContent" in (x.supported_actions or [])]
    for n in flash_models(names):
        if n not in _tried:
            _gemini["model"] = n
            return True
    return False


def model_name():
    prov = provider()
    if prov == "gemini":
        return gemini_model()
    if prov == "anthropic":
        return ANTHROPIC_MODEL
    if prov in ("openai", "groq", "openai-compatible"):
        return compat_model()
    return "none"


def save_cache():
    # merge with what is on disk first: the app and evaluate.py may run at the same time, and a plain
    # overwrite would delete the other process's answers (they would then be paid for again)
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            disk = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        disk = {}
    disk.update(cache)
    cache.update(disk)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(disk, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE_FILE)


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)  # reasoning models (Groq) think out loud
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def call_gemini(prompt, max_tokens):
    from google.genai import types
    cfg = types.GenerateContentConfig(temperature=0, max_output_tokens=max_tokens + 2000,
                                      response_mime_type="application/json")
    for attempt in range(12):  # model switches use attempts too
        try:
            r = gemini_client().models.generate_content(model=gemini_model(), contents=prompt, config=cfg)
            u = r.usage_metadata
            stats["in_tokens"] += (u.prompt_token_count or 0) if u else 0
            stats["out_tokens"] += (u.candidates_token_count or 0) if u else 0
            return r.text or ""
        except Exception as e:
            msg = str(e)
            if ("404" in msg or "NOT_FOUND" in msg) and switch_model_after_404(msg):
                print(f"    model not available, switching to {_gemini['model']}")
                continue
            if "PerDay" in msg or "per day" in msg.lower():
                # daily free-tier quota: waiting will not help. Each model has its own quota, so move to
                # the next flash model - unless the user pinned one with HESAB_GEMINI_MODEL.
                if not GEMINI_MODEL and switch_model_after_404(""):
                    print(f"    daily quota used up, switching to {_gemini['model']}")
                    continue
                raise RuntimeError("Gemini daily free-tier quota used up - try again tomorrow or use another key/model "
                                   "(HESAB_GEMINI_MODEL). Cached answers still work.") from e
            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg) and attempt < 11:
                m = re.search(r"retry in ([\d.]+)s", msg)  # Google says how long to wait
                wait = min(int(float(m.group(1))) + 2, 90) if m else 15 * (attempt + 1)
                print(f"    rate limit / busy, waiting {wait}s ... ({msg[:120]})")
                stats["retries"] += 1
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Gemini: no answer after all retries / model switches")  # never cache an empty answer


def complete(prompt, max_tokens=400):
    prov = provider()
    if prov is None:
        # no key: only cached answers can be used
        key_any = [k for k in cache if k.endswith(hashlib.sha256(prompt.encode()).hexdigest())]
        if key_any:
            stats["cached"] += 1
            return cache[key_any[0]]
        raise RuntimeError("No API key set (GEMINI_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY) and answer not in cache.")
    model = model_name()
    key = model + ":" + hashlib.sha256(prompt.encode()).hexdigest()
    if key in cache:
        stats["cached"] += 1
        return cache[key]
    if MAX_CALLS and stats["calls"] >= MAX_CALLS:
        raise RuntimeError(f"AI call budget reached ({MAX_CALLS} requests this run, HESAB_MAX_LLM_CALLS) - "
                           "remaining records go to review")
    if prov == "gemini":
        text = call_gemini(prompt, max_tokens)
    elif prov == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        # current Claude models think by default and reject non-default temperature;
        # extra headroom so thinking does not truncate the JSON answer
        r = client.messages.create(model=model, max_tokens=max_tokens + 4000,
                                   messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in r.content if b.type == "text")
        stats["in_tokens"] += r.usage.input_tokens
        stats["out_tokens"] += r.usage.output_tokens
    else:
        # OpenAI, Groq or any OpenAI-compatible service; extra headroom for reasoning models
        r = openai_client().chat.completions.create(model=model, max_tokens=max_tokens + 2000, temperature=0,
                                                    messages=[{"role": "user", "content": prompt}])
        text = r.choices[0].message.content or ""
        stats["in_tokens"] += r.usage.prompt_tokens
        stats["out_tokens"] += r.usage.completion_tokens
    stats["calls"] += 1
    key = model_name() + ":" + hashlib.sha256(prompt.encode()).hexdigest()  # model may have switched
    cache[key] = text
    save_cache()
    return text


def ask_json(prompt):
    return parse_json(complete(prompt))


def cost_usd():
    prov = provider() or "gemini"
    pin, pout = PRICES[prov]
    return stats["in_tokens"] / 1e6 * pin + stats["out_tokens"] / 1e6 * pout


EXPLAIN_PROMPT = """Sən mühasibə kömək edən ƏDV üzləşdirmə köməkçisisən. Aşağıdakı uyğunsuzluq üçün:
1) mühasib üçün 2 cümləlik izah (nə baş verib, ƏDV-yə təsiri nədir),
2) təchizatçıya göndəriləcək qısa, nəzakətli məktub (Azərbaycan dilində) yaz.
Faktları dəyişmə, yalnız verilən məlumatdan istifadə et. Hüquqi nəticə çıxarma, yoxlamağı tövsiyə et.

Uyğunsuzluq növü: {label}
Sübut: {evidence}
Portal qeydi: {portal}
1C qeydi: {onec}

YALNIZ JSON: {{"explanation": "...", "email_subject": "...", "email_body": "..."}}"""


def explain(label, evidence, portal_txt, onec_txt):
    p = EXPLAIN_PROMPT.format(label=label, evidence="; ".join(evidence), portal=portal_txt or "-", onec=onec_txt or "-")
    try:
        return parse_json(complete(p, 700)) or {"explanation": "(AI cavabı oxunmadı)", "email_subject": "", "email_body": ""}
    except Exception as e:
        return {"explanation": f"(AI izahı alınmadı: {e})", "email_subject": "", "email_body": ""}
