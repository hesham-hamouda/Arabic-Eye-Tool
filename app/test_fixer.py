"""Committed check for the Arabic visual-order fixer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixer import fix_visual_to_logical


def test_roundtrip():
    logical = "اهلا بك ياميوز"
    assert fix_visual_to_logical(fix_visual_to_logical(logical)) == logical


def test_latin_untouched():
    assert fix_visual_to_logical("hello 123") == "hello 123"


def test_mixed_roundtrip():
    logical = "Muse يقول hello 123 تمام"
    assert fix_visual_to_logical(fix_visual_to_logical(logical)) == logical


def test_preprocess_caps_width():
    from PIL import Image
    from ocr_engine import preprocess
    out = preprocess(Image.new("RGB", (1200, 800), "black"))
    assert out.size[0] <= 1600


def test_smart_fix_visual_letters():
    # Tesseract on shaped text: visual letter order -> letter-reverse wins.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fixer import pick_best
    best, variant = pick_best("الها كب زويماي")
    assert (best, variant) == ("اهلا بك ياميوز", "runs")


def test_smart_fix_word_order():
    # Glyph error + reversed words -> corrector fixes املا->اهلا,
    # scorer flips word order -> exact logical line.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fixer import pick_best
    best, variant = pick_best("ياميوز بك املا")
    assert (best, variant) == ("اهلا بك ياميوز", "words")


def test_confusion_corrector():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fixer import correct_line
    assert correct_line("ياميوز بك املا") == "ياميوز بك اهلا"
    assert correct_line("ال عربية") == "العربية"
    assert correct_line("hello 123") == "hello 123"


def test_smart_fix_idempotent():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fixer import pick_best
    best, variant = pick_best("اهلا بك ياميوز")
    assert (best, variant) == ("اهلا بك ياميوز", "as-is")


def test_terminal_format_arabic():
    # Terminal shaping (reshaper+bidi) must invert cleanly to logical text.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from terminal_reader import format_for_terminal
    from fixer import fix_visual_to_logical
    logical = "مرحبا بالعين العربية"
    shaped = format_for_terminal(logical)
    assert shaped and shaped != logical
    # bidi visual order also flips word order: invert words, then runs.
    inv = fix_visual_to_logical(" ".join(reversed(shaped.split(" "))))
    assert inv == logical
    assert format_for_terminal("ABC 123") == "ABC 123"


def test_shape_for_rich_keeps_fences():
    # Arabic prose lines are shaped; fenced code blocks stay byte-identical.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from terminal_reader import shape_for_rich
    md = "مرحبا بالعين\n```\nprint('hi')\n```\nABC 123"
    out = shape_for_rich(md).split("\n")
    assert out[2] == "print('hi')"
    assert out[0] != "مرحبا بالعين"
    assert out[-1] == "ABC 123"


def test_overlay_layout_structure():
    # Gemini-overlay layout renders header + ask bar; context pill on demand.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from rich.console import Console
    from terminal_reader import build_layout
    c = Console(width=80, height=24, record=True)
    c.print(build_layout([], "st", shaped=True))
    out = c.export_text()
    assert "Arabic Eye Tool" in out and "Ask anything" in out
    c2 = Console(width=80, height=24, record=True)
    c2.print(build_layout([("user", "hi")], "st", shaped=True,
                          attach="screen - 3 lines"))
    out2 = c2.export_text()
    assert "attached" in out2 and "screen - 3 lines" in out2


def test_list_windows_post_enum():
    # Regression: titles must be read AFTER EnumWindows (in-callback
    # GetWindowTextW returns empty for cross-thread windows).
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from desktop_eye import list_windows
    wins = list_windows()
    assert isinstance(wins, list)
    assert all(isinstance(h, int) and isinstance(t, str) for h, t in wins)


def test_error_log_tracks():
    # In-tool error tracking: one entry per failure, counted back.
    import sys
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from error_log import error_count, log_error
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "errors.log")
        assert error_count(p) == 0
        try:
            raise ValueError("boom-test")
        except ValueError as e:
            log_error("probe", e, path=p)
        assert error_count(p) == 1


def test_foreground_helpers():
    # Invalid handles are unusable; real fg handle is a positive int.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from desktop_eye import foreground_window, window_region
    assert window_region(0) is None
    assert isinstance(foreground_window(), int)


def test_desktop_helpers():
    # Pill text + RTL alignment for the desktop chat, no window needed.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from desktop_eye import is_rtl, screen_label
    assert screen_label(3) == "screen - 3 lines"
    assert screen_label(0) is None
    assert is_rtl("مرحبا") is True
    assert is_rtl("hello") is False


def test_brain_payload_arabic():
    # Brain request carries OCR context + user query, system-first.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from terminal_reader import build_brain_messages
    msgs = build_brain_messages("اشرح الخطأ",
                                [("ModuleNotFoundError: x", 90.0)])
    assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
    assert "اشرح الخطأ" in msgs[-1]["content"]
    assert "ModuleNotFoundError" in msgs[-1]["content"]
    assert "لا يوجد نص شاشة" in build_brain_messages("س", [])[-1]["content"]


def test_auto_pacing():
    import sys
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ocr_engine import frame_signature, change_ratio, static_step
    a = Image.new("RGB", (200, 100), "black")
    b = Image.new("RGB", (200, 100), "black")
    c = Image.new("RGB", (200, 100), "white")
    sa, sb, sc = (frame_signature(x) for x in (a, b, c))
    assert change_ratio(sa, sb) == 0.0
    assert change_ratio(sa, sc) > 0.5
    assert static_step(0.0, 0) == (True, 1)
    assert static_step(0.0, 2) == (False, 3)
    assert static_step(0.5, 5) == (True, 0)


if __name__ == "__main__":
    test_roundtrip()
    test_latin_untouched()
    test_mixed_roundtrip()
    test_preprocess_caps_width()
    test_smart_fix_visual_letters()
    test_smart_fix_word_order()
    test_smart_fix_idempotent()
    test_confusion_corrector()
    test_terminal_format_arabic()
    test_shape_for_rich_keeps_fences()
    test_brain_payload_arabic()
    test_overlay_layout_structure()
    test_list_windows_post_enum()
    test_error_log_tracks()
    test_foreground_helpers()
    test_desktop_helpers()
    test_auto_pacing()
    print("fixer tests: 17/17 PASS")
