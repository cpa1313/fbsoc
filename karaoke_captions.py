"""
karaoke_captions.py
Renders a caption block as a transparent RGBA image (numpy array) with one
word highlighted - used to build the "word lights up as it's spoken"
karaoke-style captions. Re-rendered once per word state, then strung
together as a sequence of short ImageClips in video_engine.py.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TEXT_COLOR = (255, 255, 255, 255)
HIGHLIGHT_COLOR = (255, 209, 64, 255)   # warm gold - classic karaoke pop
STROKE_COLOR = (0, 0, 0, 255)
STROKE_WIDTH = 3
LINE_SPACING = 14

_OUTLINE_OFFSETS = [
    (-STROKE_WIDTH, 0), (STROKE_WIDTH, 0), (0, -STROKE_WIDTH), (0, STROKE_WIDTH),
    (-STROKE_WIDTH, -STROKE_WIDTH), (STROKE_WIDTH, STROKE_WIDTH),
    (-STROKE_WIDTH, STROKE_WIDTH), (STROKE_WIDTH, -STROKE_WIDTH),
]


def _wrap_words(words, font, max_width, draw):
    """Greedy word-wrap. Returns a list of lines, each a list of word indices."""
    space_width = draw.textlength(" ", font=font)
    lines, current, current_width = [], [], 0.0
    for idx, word in enumerate(words):
        w = draw.textlength(word, font=font)
        projected = w if not current else current_width + space_width + w
        if current and projected > max_width:
            lines.append(current)
            current, current_width = [idx], w
        else:
            current.append(idx)
            current_width = projected
    if current:
        lines.append(current)
    return lines


class KaraokeLayout:
    """Wraps the line once and reuses the layout for every highlight state,
    so word positions never jitter between frames."""

    def __init__(self, words, font_path, box_width, font_size=64):
        self.words = words
        self.font = ImageFont.truetype(font_path, font_size)
        self.box_width = box_width

        probe = Image.new("RGBA", (10, 10))
        draw = ImageDraw.Draw(probe)
        self.lines = _wrap_words(words, self.font, box_width, draw)
        self.space_width = draw.textlength(" ", font=self.font)
        self.word_widths = [draw.textlength(w, font=self.font) for w in words]

        ascent, descent = self.font.getmetrics()
        self.line_height = ascent + descent + LINE_SPACING
        self.box_height = self.line_height * len(self.lines) + 10

    def render(self, highlight_idx: int | None) -> np.ndarray:
        img = Image.new("RGBA", (self.box_width, self.box_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = 5.0
        for line in self.lines:
            widths = [self.word_widths[i] for i in line]
            total_width = sum(widths) + self.space_width * (len(line) - 1)
            x = (self.box_width - total_width) / 2
            for pos, idx in enumerate(line):
                word = self.words[idx]
                color = HIGHLIGHT_COLOR if idx == highlight_idx else TEXT_COLOR
                for dx, dy in _OUTLINE_OFFSETS:
                    draw.text((x + dx, y + dy), word, font=self.font, fill=STROKE_COLOR)
                draw.text((x, y), word, font=self.font, fill=color)
                x += widths[pos] + self.space_width
            y += self.line_height

        return np.array(img)
