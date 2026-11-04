"""Arabic visual-order fixer for terminal output.

Windows consoles render Arabic logical text left-to-right without shaping,
so Arabic runs appear reversed. OCR reads that visual order. This module
converts visual order back to logical order by reversing each contiguous
Arabic-letter run. Qt displays the logical result correctly (no reshaper
needed in the overlay).
"""
from __future__ import annotations

import re
import unicodedata

_ARABIC_LETTER = (
    "\u0621-\u064a"  # main block
    "\u066e-\u06d3"  # extended letters
    "\u06fa-\u06fc"
    "\u0750-\u077f"
    "\u08a0-\u08ff"
    "\ufb50-\ufdff"
    "\ufe70-\ufeff"
)
_ARABIC_RUN_RE = re.compile(f"[{_ARABIC_LETTER}]+")
_ARABIC_ANY_RE = re.compile(f"[{_ARABIC_LETTER}\u064b-\u065f\u0670]")
_MIRROR = str.maketrans({"(": ")", ")": "(", "[": "]", "]": "[",
                          "{": "}", "}": "{", "<": ">", ">": "<"})


def contains_arabic(text: str) -> bool:
    return _ARABIC_ANY_RE.search(text) is not None


def _reverse_run(run: str) -> str:
    return run.translate(_MIRROR)[::-1]


def fix_visual_to_logical(text: str) -> str:
    """Convert terminal visual-order text back to logical order."""
    text = unicodedata.normalize("NFKC", text)
    return _ARABIC_RUN_RE.sub(lambda m: _reverse_run(m.group(0)), text)


def fix_lines(lines: list[str]) -> list[str]:
    return [fix_visual_to_logical(ln) for ln in lines]


_MARKS_RE = re.compile("[\u200e\u200f\u202a\u202b\u202c\u202d\u202e]")


def clean_ocr_marks(text: str) -> str:
    """Strip invisible direction marks Tesseract emits around RTL text."""
    return _MARKS_RE.sub("", text).strip()


_CORPUS = """اهلا_بك ياميوز مرحبا شكرا_لك تمام ماشي ازيك عامل_ايه
صباح_الخير مساء_الخير السلام_عليكم يا_قائد لو_سمحت من_فضلك تمام_كده زي_الفل
في من على الى الذي التي هذا هذه لكن جدا كل مع ما لا لم لن قد اذا عندما
يقول يعرض يظهر يقرأ يكتب يفتح يشغل يجرب يشوف يعمل ياخد
التيرمنال الماوس العدسة النص السطر القراءة النسخ التجميد المتابعة التغطية الثابتة
الشاشة النافذة الخط الصورة البرنامج الاداة المشكلة الحل الكود الرقم
عربي انجليزي خلط ترتيب مقلوب معدول صحيح دقة سرعة بطيء سريع
العربية الحروف الكلمات الجمل قراءة عميقة ترجمة
واحد اثنين ثلاثة اول ثاني فوق تحت يمين شمال هنا هناك
تشغيل ايقاف قراءة كتابة فتح حفظ نسخ لصق اضافة تحديث
كود فيجوال_ستوديو نافذة طرفية موجه_الاوامر باورشيل""".split()

_UNI: set[str] = set()
_PAIR: set[tuple[str, str]] = set()
for _phrase in _CORPUS:
    _words = _phrase.replace("_", " ").split(" ")
    _UNI.update(_words)
    for _a, _b in zip(_words, _words[1:]):
        _PAIR.add((_a, _b))


def _colloc_score(seq: str) -> int:
    """Known words + known adjacent pairs. Pairs weigh more: word order is
    what distinguishes 'اهلا بك' (runs) from 'بك اهلا' (both)."""
    words = [w for w in seq.split(" ") if w]
    hits = sum(1 for w in words if w in _UNI)
    pairs = sum(1 for a, b in zip(words, words[1:]) if (a, b) in _PAIR)
    return hits + 3 * pairs


def _arabic_seq(line: str) -> str:
    toks = [t for t in line.split(" ") if contains_arabic(t)]
    return " ".join(toks)


def pick_best(line: str) -> tuple[str, str]:
    """Try (as-is, letter-reverse, word-reverse, both); keep best scoring.

    Tesseract is inconsistent on unshaped terminal Arabic: sometimes it emits
    visual letter order, sometimes logical letters in reversed word order.
    Score each candidate with an Arabic bigram model and keep the winner.
    Returns (text, variant_name).
    """
    line = clean_ocr_marks(line)
    if not contains_arabic(line):
        return line, "as-is"
    toks = line.split(" ")
    cands = [
        ("as-is", line),
        ("runs", fix_visual_to_logical(line)),
        ("words", " ".join(reversed(toks))),
        ("both", fix_visual_to_logical(" ".join(reversed(toks)))),
    ]
    best, bname, bscore = line, "as-is", -1
    for name, cand in cands:
        cand = correct_line(cand)
        seq = _arabic_seq(cand)
        if len(seq) < 2:
            continue
        sc = _colloc_score(seq)
        if sc > bscore:
            best, bname, bscore = cand, name, sc
    return best, bname


# OCR confusion pairs observed on small isolated terminal glyphs.
# Map: OCR char -> likely intended chars (first is keep-as-is).
_CONFUSE: dict[str, list[str]] = {
    "م": ["م", "ه"],
    "ه": ["ه", "م", "ة"],
    "ة": ["ة", "ه"],
    "ا": ["ا", "أ"],
    "أ": ["أ", "ا"],
    "ي": ["ي", "ى"],
    "ى": ["ى", "ي"],
    "ء": ["", "ء"],
}


def _correct_word(word: str) -> str:
    """Single-edit confusion fix against the known-word set."""
    if word in _UNI or not contains_arabic(word):
        return word
    chars = list(word)
    for i, ch in enumerate(chars):
        for alt in _CONFUSE.get(ch, ()):
            cand = "".join(chars[:i] + [alt] + chars[i + 1 :])
            if cand in _UNI:
                return cand
    return word


def correct_line(line: str) -> str:
    """Merge a split ال prefix, then confusion-fix each Arabic word."""
    toks = line.split(" ")
    merged: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] == "ال" and i + 1 < len(toks) and "ال" + toks[i + 1] in _UNI:
            merged.append("ال" + toks[i + 1])
            i += 2
        else:
            merged.append(toks[i])
            i += 1
    return " ".join(_correct_word(t) for t in merged)


def smart_fix_line(line: str) -> str:
    best, _ = pick_best(line)
    return best
