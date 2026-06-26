"""
voiceover.py
Turns each quote line into spoken-word audio using edge-tts (Microsoft's
free, no-API-key-needed neural voices), and captures the exact start/end
time of every individual word as it's spoken - that per-word timing is
what drives the karaoke-style caption highlight in video_engine.py.

Needs outbound internet to speech.platform.bing.com at runtime, which is
open by default on GitHub Actions runners (nothing extra to configure
there). Pick a different voice with the TTS_VOICE secret/env var if you
want - browse options with: `edge-tts --list-voices`
"""

import asyncio
import os
import re
import random
import edge_tts

# Warm, expressive, natural-sounding voices that fit this genre's reflective tone.
# These are selected for emotional range, not just clarity.
# Override with the TTS_VOICE env var to pin one specific voice instead.
DEFAULT_VOICE_POOL = [
    "en-US-AriaNeural",     # Warm, expressive, great emotional range
    "en-US-JennyNeural",    # Soft, conversational, gentle delivery
    "en-GB-SoniaNeural",    # Slightly breathy, poetic feel
    "en-US-MichelleNeural", # Rich, calm, very natural
    "en-AU-NatashaNeural",  # Distinct, warm Australian tone
]

# SSML template: adds pauses between sentences, slight pitch variation,
# and a slower, more deliberate speaking rate for emotional weight.
SSML_TEMPLATE = """<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'
    xmlns:mstts='http://www.w3.org/2001/mstts'
    xml:lang='en-US'>
  <voice name='{voice}'>
    <mstts:express-as style='gentle' styledegree='1.5'>
      <prosody rate='{rate}' pitch='{pitch}'>
        {text}
      </prosody>
    </mstts:express-as>
  </voice>
</speak>"""

def pick_voice() -> str:
    forced = os.environ.get("TTS_VOICE")
    return forced if forced else random.choice(DEFAULT_VOICE_POOL)


def _add_natural_pauses(text: str) -> str:
    """Insert SSML break tags after punctuation and at natural breath points."""
    # IMPORTANT: ellipsis dots must be swapped out for a placeholder
    # BEFORE the single-dot rule runs, otherwise the single-dot rule
    # re-matches the three literal dots still sitting inside the text
    # and stacks three extra 600ms breaks on top - this was bloating
    # every ellipsis into ~2.6s of dead air and blowing up total
    # audio/video length (and frame count, hence the slow CI render).
    # Use a plain-ASCII marker (not a unicode private-use char) since
    # the text gets embedded in SSML/XML and odd code points can make
    # the TTS service choke and return no audio at all.
    ELLIPSIS_TOKEN = "ZZELLIPSISZZ"
    text = text.replace("...", ELLIPSIS_TOKEN)
    text = text.replace(",", ',<break time="400ms"/>')
    text = text.replace(".", '.<break time="600ms"/>')
    text = text.replace("?", '?<break time="600ms"/>')
    text = text.replace("!", '!<break time="500ms"/>')
    text = text.replace(ELLIPSIS_TOKEN, '...<break time="800ms"/>')
    # Add a small breath pause before conjunctions for natural rhythm
    for word in [" but ", " and ", " so ", " yet ", " or "]:
        text = text.replace(word, f'<break time="200ms"/>{word.strip()} ')
    return text


def _merge_word_timings(raw_timings: list[dict], original_text: str) -> list[dict]:
    """
    edge-tts WordBoundary events can return sub-word phoneme fragments
    instead of whole words — e.g. "for" comes back as ["fo", "r"] and
    "myself" as ["myse", "lf"]. This causes the karaoke layout to treat
    fragments as separate words, breaking mid-word across lines.

    Fix: greedily consume raw timing tokens until their stripped+lowercased
    concatenation matches each original word, then emit a single merged
    entry spanning the full start→end range of those tokens.
    """
    orig_words = re.findall(r"\S+", original_text)
    if not orig_words or not raw_timings:
        return raw_timings

    def clean(s: str) -> str:
        """Strip punctuation for comparison only."""
        return re.sub(r"[^\w'-]", "", s).lower()

    merged = []
    t_idx = 0

    for word in orig_words:
        target = clean(word)
        if not target or t_idx >= len(raw_timings):
            continue

        acc = ""
        start = raw_timings[t_idx]["start"]
        end = raw_timings[t_idx]["end"]

        while t_idx < len(raw_timings):
            tok = clean(raw_timings[t_idx]["text"])
            end = raw_timings[t_idx]["end"]
            acc += tok
            t_idx += 1
            if acc == target:
                break                  # perfect match — done
            if not target.startswith(acc):
                break                  # diverged — accept what we have

        merged.append({"text": word, "start": start, "end": end})

    return merged


async def _save_with_word_timing(
    text: str, out_path: str, voice: str, rate: str, pitch: str
) -> list[dict]:
    ssml = SSML_TEMPLATE.format(
        voice=voice,
        rate=rate,
        pitch=pitch,
        text=_add_natural_pauses(text),
    )
    communicate = edge_tts.Communicate(ssml, voice)
    raw_timings = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration come back in 100-nanosecond ticks
                start = chunk["offset"] / 10_000_000
                end = (chunk["offset"] + chunk["duration"]) / 10_000_000
                raw_timings.append({"text": chunk["text"], "start": start, "end": end})

    # Merge any sub-word phoneme fragments back into whole words.
    # edge-tts can split e.g. "for" → ["fo", "r"] when SSML break tags
    # are present nearby, causing karaoke text to split mid-word.
    word_timings = _merge_word_timings(raw_timings, text)
    return word_timings


def synthesize_line(
    text: str,
    out_path: str,
    voice: str | None = None,
    rate: str | None = None,
    pitch: str | None = None,
) -> tuple[str, list[dict]]:
    voice = voice or pick_voice()
    # Slower rate = more thoughtful, emotional delivery
    rate = rate or os.environ.get("TTS_RATE", "-8%")
    # Slight pitch drop = warmth and sincerity
    pitch = pitch or os.environ.get("TTS_PITCH", "-3Hz")
    word_timings = asyncio.run(_save_with_word_timing(text, out_path, voice, rate, pitch))
    return out_path, word_timings


def synthesize_scenes(
    scenes: list[dict], out_dir: str, voice: str | None = None
) -> list[dict]:
    """
    scenes: [{"text": ..., "image_path": ...}, ...]
    Returns the same list with "voice_path" and "word_timings" added per scene.
    All lines in one video use the same voice for consistency.
    """
    os.makedirs(out_dir, exist_ok=True)
    chosen_voice = voice or pick_voice()
    enriched = []
    for i, scene in enumerate(scenes):
        voice_path = os.path.join(out_dir, f"voice_{i:02d}.mp3")
        _, word_timings = synthesize_line(scene["text"], voice_path, voice=chosen_voice)
        enriched.append({**scene, "voice_path": voice_path, "word_timings": word_timings})
    return enriched
