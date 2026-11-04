"""Arabic Eye Tool terminal interface — local Arabic screen reader as a chat TUI.

Pipeline, all on this machine (no cloud):
  mss screenshot (Pillow ImageGrab fallback) -> sandra_capture.png
  -> indra-ocr (Tesseract fallback) -> fixer.smart_fix_line
  -> arabic-reshaper + python-bidi shaping -> Rich chat panels.

Usage:
  python app/terminal_reader.py                 # interactive chat
  python app/terminal_reader.py --once          # one read + response card
  python app/terminal_reader.py --region 0 0 900 400
  python app/terminal_reader.py --logical       # no reshaping (Windows
                                                # Terminal shapes Arabic
                                                # natively; legacy conhost
                                                # needs shaping)
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

from PIL import Image
from rich.console import Console
from rich.layout import Layout
from rich.markdown import Markdown
from rich.panel import Panel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixer import contains_arabic, smart_fix_line
from ocr_engine import ocr_lines

CAPTURE_NAME = "sandra_capture.png"
HISTORY_KEEP = 20

# --- Smart Ant brain: Qwen2.5-0.5B in-process, LM Studio fallback ---
# Smallest Arabic-capable phone-class ant (0.5B, 988MB), verified 2026-11-04:
# answers Arabic correctly where moondream babbles. LM Studio serves GGUF
# only, so this safetensors brain loads here via transformers (already
# installed). Ollama is forbidden here and is never touched.
QWEN_PATH = (r"D:\Intelligence models\huggingface\models--Qwen--"
             r"Qwen2.5-0.5B-Instruct\snapshots\7ae557604adf67be"
             r"50417f59c2c2f167def9a775")
BRAIN_FALLBACK_MODEL = "lfm3-1.7b"  # next-smallest Arabic ant on LM Studio
BRAIN_FALLBACK_ENDPOINT = "http://127.0.0.1:1234/v1/chat/completions"
BRAIN_MAX_NEW_TOKENS = 200
BRAIN_SYSTEM = (
    "انت مساعد برمجة عربي داخل اداة Arabic Eye. عندك نص شاشة التيرمنال. "
    "اجب بالعربية فقط دائما. اشرح الاخطاء والاكواد بالعربية باختصار "
    "ودقة، واكتب المطالبات الاحترافية عندما يطلب. لا تخترع اسماء "
    "ملفات او اوامر غير مذكورة."
)

_brain = None
_brain_failed = False


def build_brain_messages(query: str,
                         ocr: list[tuple[str, float]]) -> list[dict]:
    """Pure payload builder: OCR context + user query (testable, no I/O)."""
    ctx = "\n".join(t for t, _ in ocr) if ocr else "(لا يوجد نص شاشة بعد)"
    return [
        {"role": "system", "content": BRAIN_SYSTEM},
        {"role": "user",
         "content": "نص الشاشة:\n%s\n\nسؤال المستخدم: %s" % (ctx, query)},
    ]


def _brain_load():
    """Lazy singleton: (tokenizer, model), or None when unusable."""
    global _brain, _brain_failed
    if _brain is not None or _brain_failed:
        return _brain
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(QWEN_PATH,
                                            trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            QWEN_PATH, torch_dtype="auto",
            device_map="auto", trust_remote_code=True)
        _brain = (tok, model)
    except Exception:
        _brain = None
        _brain_failed = True
    return _brain


def _brain_answer_local(msgs: list[dict]) -> str | None:
    """Run the 0.5B ant in-process; None -> use the LM Studio fallback."""
    loaded = _brain_load()
    if loaded is None:
        return None
    try:
        import torch
        tok, model = loaded
        enc = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_tensors="pt")
        ids = enc["input_ids"]
        if not torch.is_tensor(ids):
            ids = torch.tensor([ids])
        ids = ids.to(model.device)
        out = model.generate(ids, max_new_tokens=BRAIN_MAX_NEW_TOKENS,
                             do_sample=False)
        return tok.decode(out[0][len(ids[0]):],
                          skip_special_tokens=True).strip() or None
    except Exception:
        return None


def _brain_fallback_http(msgs: list[dict]) -> str:
    """LM Studio fallback ant (thinking model: leave room to think)."""
    import json
    import urllib.request
    body = json.dumps({
        "model": BRAIN_FALLBACK_MODEL, "temperature": 0.0,
        "max_tokens": 1500, "messages": msgs,
    }).encode()
    req = urllib.request.Request(BRAIN_FALLBACK_ENDPOINT, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            msg = json.load(r)["choices"][0]["message"]
    except Exception as e:
        return ("تعذر الوصول لأي نموذج (محلي: فشل التحميل، "
                "LM Studio: %s). تأكد ان LM Studio شغال." % e)
    text = (msg.get("content") or "").strip()
    if not text:
        tail = (msg.get("reasoning_content") or "").strip().split("\n")
        text = "\n".join(tail[-8:]).strip()
    return text or "رد فارغ من النموذج."


def ask_brain(query: str, ocr: list[tuple[str, float]]) -> str:
    """OCR context + query -> Ant answer. Local 0.5B first, LM Studio backup."""
    return (_brain_answer_local(build_brain_messages(query, ocr))
            or _brain_fallback_http(build_brain_messages(query, ocr)))

console = Console()

try:
    import arabic_reshaper as _reshaper
    from bidi.algorithm import get_display as _bidi_display
    _HAS_SHAPING = True
except Exception:
    _HAS_SHAPING = False


def capture_engine() -> str:
    """Name of the capture backend that would be used right now."""
    try:
        import mss  # noqa: F401
        return "mss"
    except Exception:
        return "pillow"


def ocr_backend() -> str:
    """Name of the OCR backend that would be used right now."""
    try:
        import indra_ocr  # noqa: F401
        return "indra-ocr"
    except Exception:
        return "tesseract"


def capture_screen(save_path: str = CAPTURE_NAME,
                   region: tuple[int, int, int, int] | None = None
                   ) -> tuple[Image.Image, str]:
    """Capture the screen, save it, return (image, engine_name).

    Primary engine is mss (fast, Windows-compatible); when mss is missing
    or fails, Pillow's ImageGrab is used so the script keeps working.
    region = (x, y, width, height) in absolute screen pixels.
    """
    img: Image.Image | None = None
    engine = "mss"
    try:
        import mss as _mss
        _factory = getattr(_mss, "MSS", None) or _mss.mss
        with _factory() as sct:
            if region is None:
                box = sct.monitors[1]
            else:
                x, y, w, h = region
                box = {"left": x, "top": y, "width": w, "height": h}
            shot = sct.grab(box)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception:
        img = None
        engine = "pillow"
    if img is None:
        from PIL import ImageGrab
        if region is None:
            img = ImageGrab.grab()
        else:
            x, y, w, h = region
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(save_path)
    return img, engine


def format_for_terminal(text: str, shaped: bool = True) -> str:
    """Prepare logical Arabic text for terminal printing.

    Legacy Windows consoles (conhost) do not shape Arabic, so reshape +
    bidi-reorder into visual order before printing. Terminals with native
    shaping (Windows Terminal) should pass shaped=False (--logical).
    """
    if not shaped or not _HAS_SHAPING or not contains_arabic(text):
        return text
    return _bidi_display(_reshaper.reshape(text))


def shape_for_rich(markdown_text: str, shaped: bool = True) -> str:
    """Shape Arabic lines for Rich renderables, leaving code fences alone."""
    if not shaped or not _HAS_SHAPING:
        return markdown_text
    out, in_fence = [], False
    for line in markdown_text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and contains_arabic(line):
            out.append(_bidi_display(_reshaper.reshape(line)))
        else:
            out.append(line)
    return "\n".join(out)


def read_screen(save_path: str = CAPTURE_NAME,
                region: tuple[int, int, int, int] | None = None,
                shaped: bool = True) -> tuple[list[tuple[str, float]], str]:
    """One full pass: capture -> OCR -> fix -> terminal-ready lines."""
    img, engine = capture_screen(save_path, region)
    out = []
    for text, conf in ocr_lines(img):
        fixed = smart_fix_line(text)
        if fixed.strip():
            out.append((format_for_terminal(fixed, shaped), conf))
    return out, engine


def read_screen_logical(save_path: str = CAPTURE_NAME,
                        region: tuple[int, int, int, int] | None = None
                        ) -> tuple[list[tuple[str, float]], str]:
    """Capture -> OCR -> fix, returning logical-order lines for Markdown."""
    img, engine = capture_screen(save_path, region)
    out = []
    for text, conf in ocr_lines(img):
        fixed = smart_fix_line(text)
        if fixed.strip():
            out.append((fixed, conf))
    return out, engine


def response_markdown(lines: list[tuple[str, float]], engine: str) -> str:
    """Build the AI-response Markdown body from OCR lines."""
    if not lines:
        return "No text found on screen."
    avg = sum(c for _, c in lines) / len(lines)
    body = ["### Screen read — %d lines (avg %.0f%%, `%s`)"
            % (len(lines), avg, engine)]
    for text, conf in lines:
        body.append("- [%.0f%%] %s" % (conf, text))
    return "\n".join(body)


def build_layout(history: list[tuple[str, str]], status: str,
                 shaped: bool = True, attach: str | None = None) -> Layout:
    """Gemini-overlay style: top bar, answer area, context pill, ask bar."""
    from rich.box import ROUNDED
    lay = Layout()
    rows = [
        Layout(Panel("  Alt + Space",
                     title="Arabic Eye Tool", subtitle=status,
                     border_style="white", box=ROUNDED, height=4),
               name="header", size=4),
        Layout(name="body", ratio=1),
    ]
    if attach:
        rows.append(Layout(Panel(attach, title="attached",
                                 border_style="blue", box=ROUNDED,
                                 height=3),
                           name="context", size=3))
    rows.append(Layout(Panel("Enter = screenshot  -  type to ask  -  q = quit",
                             title="input", border_style="white",
                             box=ROUNDED, height=3),
                       name="footer", size=3))
    lay.split_column(*rows)
    if not history:
        lay["body"].update(Panel("Ask anything...",
                                 border_style="dim", box=ROUNDED))
    else:
        from rich.console import Group
        cards = []
        for role, md in history[-HISTORY_KEEP:]:
            if role == "user":
                cards.append(Panel(shape_for_rich(md, shaped),
                                   title="You", border_style="blue",
                                   box=ROUNDED))
            else:
                cards.append(Panel(Markdown(shape_for_rich(md, shaped)),
                                   title="Arabic Eye",
                                   border_style="white", box=ROUNDED))
        lay["body"].update(Group(*cards))
    return lay


def think_and_read(save_path: str, region, shaped: bool):
    """Capture + OCR under a Thinking spinner; return (md, engine, lines)."""
    with console.status("[bold blue]Thinking...[/]", spinner="dots"):
        lines, engine = read_screen_logical(save_path, region)
    return response_markdown(lines, engine), engine, lines


def think_and_ask(query: str, ocr: list[tuple[str, float]]) -> str:
    """Brain answer under a Thinking spinner."""
    with console.status("[bold blue]Thinking...[/]", spinner="dots"):
        return ask_brain(query, ocr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Arabic Eye Tool local reader")
    ap.add_argument("--once", action="store_true", help="single read, then exit")
    ap.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                    help="capture region in screen pixels")
    ap.add_argument("--out", default=CAPTURE_NAME, help="capture file name")
    ap.add_argument("--logical", action="store_true",
                    help="print logical text (for Windows Terminal)")
    args = ap.parse_args(argv)
    region = tuple(args.region) if args.region else None
    shaped = not args.logical
    status = ("capture: %s | ocr: %s | brain: qwen-0.5b | %s"
              % (capture_engine(), ocr_backend(),
                 datetime.datetime.now().strftime("%H:%M")))

    if args.once:
        md, _, lines = think_and_read(args.out, region, shaped)
        attach = ("screen - %d lines" % len(lines)) if lines else None
        console.print(build_layout([], status, shaped, attach))
        from rich.box import ROUNDED
        console.print(Panel(Markdown(shape_for_rich(md, shaped)),
                            title="Arabic Eye", border_style="white",
                            box=ROUNDED))
        return 0

    history: list[tuple[str, str]] = []
    last_ocr: list[tuple[str, float]] = []
    attach: str | None = None
    while True:
        console.print(build_layout(history, status, shaped, attach))
        try:
            cmd = console.input("[bold]Ask anything... [/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        low = cmd.lower()
        if low in ("q", "quit", "exit"):
            break
        if low == "clear":
            history = []
            continue
        if low == "logical":
            shaped = not shaped
            status += " | shaping=%s" % ("on" if shaped else "off")
            continue
        if low in ("", "s", "screenshot", "read"):
            history.append(("user", "Read my screen"))
            md, _, last_ocr = think_and_read(args.out, region, shaped)
            attach = (("screen - %d lines" % len(last_ocr))
                      if last_ocr else None)
            history.append(("ai", md))
        else:
            history.append(("user", cmd))
            if not last_ocr:
                _, _, last_ocr = think_and_read(args.out, region, shaped)
            history.append(("ai", think_and_ask(cmd, last_ocr)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
