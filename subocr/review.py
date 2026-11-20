"""Read-only warnings for OCR results; never correct or merge subtitle text."""
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
import re
import string

from .core import has_han, normalized


DICTIONARY_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'dictionaries' / 'en_frequency.txt'
ACCEPTED_WORDS_PATH = Path(__file__).resolve().parents[1] / 'accepted_words.txt'
ROW_COLORS = {'red': '#ffe3e3', 'orange': '#ffe8cc', 'yellow': '#fff7db', 'none': '#ffffff'}
WORDS = re.compile(r"(?<![\w’'])[A-Za-z]+(?:[’'][A-Za-z]+)*(?![\w’'])")


def confidence_label(value, detailed=False):
    if value < .80 and round(value * 100, 1) >= 80:
        return '<80%'
    return f'{value:.1%}' if detailed or .795 <= value < .80 else f'{value:.0%}'


def accepted_words(text):
    """One word/name per line, with optional # comments; phrases accept each word."""
    return {match.group().casefold().replace('’', "'")
            for line in text.splitlines() for match in WORDS.finditer(line.split('#', 1)[0])}


@lru_cache(maxsize=1)
def english_frequencies():
    with DICTIONARY_PATH.open(encoding='utf-8-sig') as source:
        return {word: int(count) for word, count in (line.split() for line in source)}


@dataclass(frozen=True)
class SpellingWarning:
    word: str
    suggestion: str


class EnglishSpellChecker:
    """Conservative dictionary hints, including common OCR omissions such as flm.

    Unknown words are flagged only when one edit away from a common word.
    Acronyms, numbers and likely proper names are exempt; a user allowlist can
    protect names that look like ordinary spelling errors. Chinese is ignored.
    """
    def __init__(self, accepted=()):
        self.accepted = set(accepted)

    @staticmethod
    @lru_cache(maxsize=8192)
    def candidates(word):
        splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
        edits = {left + right[1:] for left, right in splits if right}
        edits.update(left + right[1] + right[0] + right[2:]
                     for left, right in splits if len(right) > 1)
        edits.update(left + letter + right[1:] for left, right in splits if right
                     for letter in string.ascii_lowercase)
        edits.update(left + letter + right for left, right in splits for letter in string.ascii_lowercase)
        dictionary = english_frequencies()
        return tuple(sorted(((dictionary[candidate], candidate) for candidate in edits
                             if dictionary.get(candidate, 0) >= 1_000_000),
                            key=lambda item: (-item[0], item[1])))

    def known(self, word):
        if word in self.accepted or word in english_frequencies():
            return True
        if "'" not in word:
            return False
        if word == "let's":
            return True
        if word.endswith("n't"):
            root = {'ca': 'can', 'wo': 'will', 'sha': 'shall'}.get(word[:-3], word[:-3])
        else:
            root, suffix = word.rsplit("'", 1)
            if suffix not in {'s', 're', 've', 'll', 'd', 'm'}:
                return False
        return root in self.accepted or root in english_frequencies()

    def check(self, text):
        warnings, seen = [], set()
        for match in WORDS.finditer(text):
            token = match.group().replace('’', "'")
            word = token.casefold()
            if word in seen or len(word) < 3 or len(word) > 30 or token.isupper() or self.known(word):
                continue
            seen.add(word)
            # Do not treat unknown capitalized names in the middle of a sentence
            # as mistakes merely because they are absent from the dictionary.
            before = text[:match.start()].rstrip()
            sentence_start = not before or before[-1] in '.!?。！？'
            if token[0].isupper() and not sentence_start:
                continue
            if token[0].isupper() and not token.istitle():
                continue
            candidates = self.candidates(word)
            # At sentence starts, demand a particularly common alternative to
            # avoid highlighting names such as Kunzi, Seko or Orochi.
            minimum = 50_000_000 if token[0].isupper() else 1_000_000
            if candidates and candidates[0][0] >= minimum:
                warnings.append(SpellingWarning(match.group(), candidates[0][1]))
        return tuple(warnings)


def similar_content(first, second):
    first, second = normalized(first), normalized(second)
    if not first or not second:
        return False
    if first == second:
        return True
    length = min(len(first), len(second))
    matcher = SequenceMatcher(None, first, second, autojunk=False)
    # Short Han captions lose over 10% similarity from a single OCR substitution.
    # This only warns for manual review; extraction/automatic merging stays strict.
    if has_han(first) and has_han(second) and 5 <= length <= 20:
        budget = 1 if length < 8 else 2
        if abs(len(first) - len(second)) <= budget:
            previous = list(range(len(second) + 1))
            for i, a in enumerate(first, 1):
                current = [i]
                for j, b in enumerate(second, 1):
                    current.append(min(current[-1] + 1, previous[j] + 1,
                                       previous[j - 1] + (a != b)))
                if min(current) > budget:
                    break
                previous = current
            else:
                if previous[-1] <= budget:
                    return True
    if length < 6:
        return False
    return matcher.ratio() >= .90


@dataclass(frozen=True)
class RowReview:
    level: str
    reasons: tuple[str, ...]

    @property
    def color(self):
        return ROW_COLORS[self.level]


def review_rows(cues, checker):
    """Both neighbors get duplicate warnings, irrespective of OCR confidence.

    Legacy Cue.review/edited flags deliberately have no effect on row colors.
    """
    neighbors = [[] for _ in cues]
    for row in range(1, len(cues)):
        if similar_content(cues[row - 1].text, cues[row].text):
            neighbors[row - 1].append(row + 1)
            neighbors[row].append(row)
    result = []
    for row, cue in enumerate(cues):
        low_confidence = cue.confidence < .80
        spelling = checker.check(cue.text)
        reasons = []
        if low_confidence:
            reasons.append(f'Đỏ: điểm OCR {confidence_label(cue.confidence, detailed=True)}, thấp hơn 80%.')
        if spelling:
            words = '; '.join(f'{issue.word} (gợi ý: {issue.suggestion})' for issue in spelling)
            reasons.append(f'Cam: từ nghi sai chính tả: {words}. Chỉ cảnh báo, chưa sửa chữ.')
        if neighbors[row]:
            rows = ', '.join(map(str, neighbors[row]))
            reasons.append(f'Vàng: nội dung gần giống đoạn liền kề số {rows}.')
        level = 'red' if low_confidence else 'orange' if spelling else 'yellow' if neighbors[row] else 'none'
        result.append(RowReview(level, tuple(reasons)))
    return result
