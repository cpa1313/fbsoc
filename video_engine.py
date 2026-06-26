"""
video_engine.py
Builds a vertical (9:16) aesthetic quote video from a list of
{"text", "image_path", "voice_path", "word_timings"} scenes.

- Each scene = one background image with a slow "Ken Burns" zoom
- The quote line lights up word-by-word in sync with the narration
  (karaoke style), using the per-word timing edge-tts reports
- Scene length matches the spoken audio (plus breathing room)
- Background music plays under the narration at low volume the whole way
- A small watermark sits near the bottom
"""

import random
import numpy as np
from PIL import Image
from moviepy import (
    ImageClip,
    VideoClip,
    TextClip,
    CompositeVideoClip,
    CompositeAudioClip,
    AudioFileClip,
    concatenate_videoclips,
    concatenate_audioclips,
    vfx,
    afx,
)

from karaoke_captions import KaraokeLayout

# Output is sized for Reels / TikTok / Shorts
W, H = 720, 1280  # 720p still looks great on mobile, renders ~2x faster

LEAD_IN = 0.25            # silence before each line starts speaking
TAIL_PAD = 0.35           # breathing room after each line finishes speaking
MIN_SCENE_DURATION = 2.6  # floor, used when there's no voice track at all
NO_VOICE_DURATION = 3.4   # fallback duration per scene if no voiceover was generated
FADE_DURATION = 0.35      # caption fade in/out
ZOOM_PER_SECOND = 0.018   # how fast the Ken Burns zoom creeps in
MUSIC_VOLUME_WITH_VOICE = 0.15
MUSIC_VOLUME_NO_VOICE = 0.55
CAPTION_BOX_WIDTH = int(W * 0.84)
MIN_WORD_STATE_DURATION = 0.06  # guard against zero/negative durations from noisy timing data


def _ken_burns_clip(image_path: str, duration: float) -> VideoClip:
    """
    Load an image, cover the W×H frame, apply a slow Ken Burns zoom.

    KEY OPTIMISATION: instead of MoviePy's vfx.Resize(lambda t: …) which
    calls PIL.Image.resize() on *every single frame* (10 000+ times for a
    long video), we:
      1. Resize the source image to its largest needed size exactly ONCE
         using high-quality LANCZOS.
      2. Return a VideoClip whose make_frame crops a progressively
         smaller centre rectangle from that pre-scaled numpy array and
         rescales it to W×H with fast BILINEAR interpolation.
    The crop+resize is still per-frame but BILINEAR on a small crop is
    ~3-4× faster than LANCZOS on the full image, and we skip all of
    MoviePy's clip-chain overhead.
    """
    img = Image.open(image_path).convert("RGB")

    # --- cover-fit to frame ------------------------------------------------
    scale = max(W / img.width, H / img.height)
    fit_w = int(img.width * scale)
    fit_h = int(img.height * scale)

    # Add headroom for the maximum zoom we'll ever need (+ safety margin).
    max_zoom = 1.03 + ZOOM_PER_SECOND * duration
    safety = 1.1
    src_w = max(fit_w, int(W * max_zoom * safety))
    src_h = max(fit_h, int(H * max_zoom * safety))

    # ONE high-quality resize up front – never again.
    img_arr = np.array(img.resize((src_w, src_h), Image.LANCZOS))

    zoom_start = random.uniform(1.0, 1.03)
    cx, cy = src_w // 2, src_h // 2

    def make_frame(t):
        z = zoom_start + ZOOM_PER_SECOND * t
        # Crop a region whose size shrinks as zoom increases.
        cw = int(W / z)
        ch = int(H / z)
        x1 = max(0, cx - cw // 2)
        y1 = max(0, cy - ch // 2)
        # Clamp so we never run off the edge.
        x1 = min(x1, src_w - cw)
        y1 = min(y1, src_h - ch)
        crop = img_arr[y1: y1 + ch, x1: x1 + cw]
        # BILINEAR is ~3× faster than LANCZOS; the tiny zoom difference
        # is invisible on a mobile screen at 24 fps.
        return np.array(Image.fromarray(crop).resize((W, H), Image.BILINEAR))

    return VideoClip(make_frame, duration=duration)


def _static_caption_clip(text: str, font_path: str, duration: float) -> TextClip:
    """Plain whole-line caption, used as a fallback when no word-timing data exists."""
    txt = TextClip(
        font=font_path,
        text=text,
        font_size=64,
        size=(CAPTION_BOX_WIDTH, None),
        color="white",
        stroke_color="black",
        stroke_width=2,
        method="caption",
        text_align="center",
        horizontal_align="center",
        vertical_align="center",
        interline=8,
    ).with_duration(duration)
    txt = txt.with_position(("center", "center"))
    txt = txt.with_effects([vfx.CrossFadeIn(FADE_DURATION), vfx.CrossFadeOut(FADE_DURATION)])
    return txt


def _karaoke_caption_clip(text: str, word_timings: list[dict], font_path: str,
                           scene_duration: float) -> CompositeVideoClip:
    """
    Builds the word-by-word highlighted caption as a sequence of short
    ImageClips (one per word state), so the highlighted word lights up
    exactly when edge-tts reports that word being spoken.

    KEY OPTIMISATION: concatenate with method="chain" instead of
    method="compose".  All state clips are the same pixel size, so
    "chain" works perfectly and skips the per-frame composite lookup
    that "compose" imposes – easily 3-5× faster for long captions.
    """
    words = [w["text"] for w in word_timings]
    layout = KaraokeLayout(words, font_path, CAPTION_BOX_WIDTH)

    segments = []  # (highlight_idx_or_None, duration)

    # Silence before the first word actually starts speaking.
    pre_duration = LEAD_IN + word_timings[0]["start"]
    segments.append((None, max(pre_duration, MIN_WORD_STATE_DURATION)))

    for i, w in enumerate(word_timings):
        if i + 1 < len(word_timings):
            duration = word_timings[i + 1]["start"] - w["start"]
        else:
            duration = w["end"] - w["start"]
        segments.append((i, max(duration, MIN_WORD_STATE_DURATION)))

    spoken_until = LEAD_IN + word_timings[-1]["end"]
    tail_duration = scene_duration - spoken_until
    if tail_duration > 0:
        segments.append((None, tail_duration))

    # Normalize so segments sum exactly to scene_duration (avoids drift).
    total = sum(d for _, d in segments)
    scale = scene_duration / total if total > 0 else 1.0

    state_clips = []
    for highlight_idx, dur in segments:
        img = layout.render(highlight_idx)
        state_clips.append(ImageClip(img).with_duration(dur * scale))

    # "chain" is O(log n) per frame lookup vs "compose" which re-evaluates
    # the full composite stack every frame. Same-size clips → chain is safe.
    caption_track = concatenate_videoclips(state_clips, method="chain")
    caption_track = caption_track.with_effects([vfx.CrossFadeIn(FADE_DURATION), vfx.CrossFadeOut(FADE_DURATION)])
    caption_track = caption_track.with_position(("center", "center"))
    return caption_track


def _watermark_clip(text: str, font_path: str, duration: float) -> TextClip:
    wm = TextClip(
        font=font_path,
        text=text,
        font_size=30,
        color="white",
        method="label",
    ).with_duration(duration).with_opacity(0.75)
    wm = wm.with_position(("center", H - 110))
    return wm


def _scene_duration(scene: dict) -> float:
    voice_path = scene.get("voice_path")
    if not voice_path:
        return NO_VOICE_DURATION
    voice_clip = AudioFileClip(voice_path)
    spoken_length = voice_clip.duration
    voice_clip.close()
    return max(MIN_SCENE_DURATION, LEAD_IN + spoken_length + TAIL_PAD)


def build_video(scenes: list[dict], font_path: str, watermark_text: str,
                 music_path: str | None, out_path: str) -> str:
    scene_clips = []
    narration_clips = []
    t_cursor = 0.0
    has_voice = any(s.get("voice_path") for s in scenes)

    for scene in scenes:
        duration = _scene_duration(scene)

        bg = _ken_burns_clip(scene["image_path"], duration)

        word_timings = scene.get("word_timings")
        if word_timings:
            cap = _karaoke_caption_clip(scene["text"], word_timings, font_path, duration)
        else:
            cap = _static_caption_clip(scene["text"], font_path, duration)

        wm = _watermark_clip(watermark_text, font_path, duration)
        scene_clips.append(CompositeVideoClip([bg, cap, wm], size=(W, H)))

        voice_path = scene.get("voice_path")
        if voice_path:
            narration_clips.append(AudioFileClip(voice_path).with_start(t_cursor + LEAD_IN))

        t_cursor += duration

    # "chain" is correct here: all scene CompositeVideoClips are W×H and
    # sequential with no overlap, so there is no need for "compose" which
    # pays a heavy per-frame compositing tax across the full clip list.
    video = concatenate_videoclips(scene_clips, method="chain")
    total_duration = video.duration

    audio_tracks = []
    if narration_clips:
        audio_tracks.append(CompositeAudioClip(narration_clips))

    if music_path:
        music = AudioFileClip(music_path)
        if music.duration >= total_duration:
            music = music.subclipped(0, total_duration)
        else:
            reps = int(total_duration // music.duration) + 1
            music = concatenate_audioclips([music] * reps).subclipped(0, total_duration)
        music = music.with_effects([afx.AudioFadeOut(1.2), afx.AudioFadeIn(0.8)])
        music = music.with_volume_scaled(MUSIC_VOLUME_WITH_VOICE if has_voice else MUSIC_VOLUME_NO_VOICE)
        audio_tracks.append(music)

    if audio_tracks:
        final_audio = audio_tracks[0] if len(audio_tracks) == 1 else CompositeAudioClip(audio_tracks)
        video = video.with_audio(final_audio)

    video.write_videofile(
        out_path,
        fps=24,               # 24fps is cinematic standard, no need for 30
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",   # much faster encode, barely any quality loss for social video
        threads=4,
    )
    return out_path
