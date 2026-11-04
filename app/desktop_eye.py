"""Arabic Eye Tool desktop app — window, app menu, chat (tkinter only).

No console, no installs: stdlib tkinter + the local pipeline
(mss capture, indra-ocr/Tesseract, fixer, Qwen2.5-0.5B brain).
Run it with:  pythonw app\\desktop_eye.py   (or double-click run.bat)

Layout (Gemini-overlay style, light theme):
  top bar: app menu (open windows) + Refresh
  Read screen button + status line
  chat area (You blue / Arabic Eye black, Arabic lines right-aligned)
  attached-context pill + Ask-anything entry + blue Send button
"""
from __future__ import annotations

import ctypes
import queue
import threading
import tkinter as tk
from ctypes import wintypes
from tkinter import ttk

from error_log import error_count, log_error
from fixer import contains_arabic, smart_fix_line
from ocr_engine import ocr_lines
from terminal_reader import ask_brain, capture_screen, shape_for_rich

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

BLUE = "#1a73e8"
INK = "#202124"
GRAY = "#80868b"


def screen_label(n: int) -> str | None:
    """Attached-context pill text; None when there is nothing to show."""
    return ("screen - %d lines" % n) if n else None


def is_rtl(text: str) -> bool:
    """True when a chat line should be right-aligned (Arabic)."""
    return contains_arabic(text)


def list_windows() -> list[tuple[int, str]]:
    """Visible top-level windows with a title, terminals/editors first.

    Reads happen AFTER EnumWindows returns (in-callback cross-thread
    GetWindowTextW is unreliable). NOTE 2026-11-04: an earlier revision
    silently returned [] because the hwnd argument was missing from the
    GetWindowTextW call — always pass (hwnd, buf, size).
    """
    hwnds: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        hwnds.append(hwnd)
        return True

    try:
        ctypes.windll.user32.EnumWindows(cb, 0)
    except Exception:
        return []
    out: list[tuple[int, str]] = []
    for hwnd in hwnds:
        try:
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                continue
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value.strip()
            if len(title) <= 2:
                continue
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left > 200 and r.bottom - r.top > 100:
                out.append((hwnd, title))
        except Exception:
            continue
    keys = ("code", "visual studio", "terminal", "powershell", "cmd",
            "windows terminal", "cascadia", "conhost", "ubuntu", "wsl",
            "chrome", "edge", "firefox", "browser")
    out.sort(key=lambda t: (0 if any(k in t[1].lower() for k in keys) else 1,
                            t[1].lower()))
    return out


def foreground_window() -> int:
    """HWND of the current foreground window (works even when blind)."""
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return 0


def window_region(hwnd: int) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of a window in physical pixels, or None if gone."""
    try:
        r = wintypes.RECT()
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return None
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w < 200 or h < 100:
            return None
        return (r.left, r.top, w, h)
    except Exception:
        return None


def read_window(hwnd: int) -> list[tuple[str, float]]:
    """OCR the chosen app window; logical-order fixed lines."""
    region = window_region(hwnd)
    if region is None:
        raise RuntimeError("window is gone - pick another app")
    from PIL import Image  # noqa: F401  (kept for parity with ocr_engine)
    img, _engine = capture_screen("sandra_capture.png", region)
    out = []
    for text, conf in ocr_lines(img):
        fixed = smart_fix_line(text)
        if fixed.strip():
            out.append((fixed, conf))
    return out


class Eye(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Arabic Eye Tool")
        self.geometry("540x700")
        self.configure(bg="white")
        self._hwnds: dict[str, int] = {}
        self._hwnd = 0
        self._last_ocr: list[tuple[str, float]] = []
        self._jobs: "queue.Queue[tuple]" = queue.Queue()

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="white")
        style.configure("TLabel", background="white", foreground=INK,
                        font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("TCombobox", font=("Segoe UI", 10))

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="App:").pack(side="left")
        self.combo = ttk.Combobox(top, state="readonly", width=38)
        self.combo.pack(side="left", padx=6)
        ttk.Button(top, text="Refresh",
                   command=self.refresh).pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self._on_pick)
        self.combo.bind("<Button-1>", lambda _e: self.refresh())

        row = ttk.Frame(self, padding=(8, 0, 8, 0))
        row.pack(fill="x")
        self.read_btn = tk.Button(row, text="Read screen", bg=BLUE, fg="white",
                                  activebackground="#1765cc",
                                  activeforeground="white", relief="flat",
                                  font=("Segoe UI", 10, "bold"),
                                  padx=12, pady=4, command=self.do_read)
        self.read_btn.pack(side="left")
        tk.Button(row, text="Read fg in 3s", bg="#e8f0fe", fg=BLUE,
                  activebackground="#d2e3fc", relief="flat",
                  font=("Segoe UI", 10),
                  padx=12, pady=4, command=self.do_read_fg).pack(
                      side="left", padx=(6, 0))
        self.status = ttk.Label(row, text="Pick an app, then Read.",
                                foreground=GRAY)
        self.status.pack(side="left", padx=8)

        import tkinter.scrolledtext as st
        self.chat = st.ScrolledText(self, wrap="word", bg="white", fg=INK,
                                    font=("Segoe UI", 11), relief="flat",
                                    padx=10, pady=10, state="disabled")
        self.chat.pack(fill="both", expand=True, padx=8, pady=8)
        self.chat.tag_config("user", foreground=BLUE,
                             font=("Segoe UI", 11, "bold"))
        self.chat.tag_config("ai", foreground=INK)
        self.chat.tag_config("meta", foreground=GRAY)
        self.chat.tag_config("right", justify="right")

        self.pill = ttk.Label(self, text="", foreground=BLUE,
                              font=("Segoe UI", 9))
        self.pill.pack(fill="x", padx=10)

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        self.entry = ttk.Entry(bottom, font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.insert(0, "Ask anything...")
        self.entry.bind("<FocusIn>", self._clear_hint)
        self.entry.bind("<Return>", lambda _e: self.do_ask())
        tk.Button(bottom, text="Send", bg=BLUE, fg="white",
                  activebackground="#1765cc", activeforeground="white",
                  relief="flat", font=("Segoe UI", 10, "bold"),
                  padx=14, command=self.do_ask).pack(side="left", padx=(6, 0))

        import sys as _sys
        _sys.excepthook = self._on_uncaught
        self.refresh()
        self._retries = 0
        self.after(1500, self._retry_menu)
        self.after(200, self._poll)
        self._say("Pick an app from the menu and press Read screen.",
                  "meta")

    def _retry_menu(self):
        """Keep healing: fast retries first, then every 30s until fed."""
        if self._hwnds:
            return
        self._retries += 1
        self.refresh()
        if self._hwnds:
            return
        gap = [1500, 3000, 5000, 10000, 20000][min(self._retries - 1, 4)] \
            if self._retries <= 5 else 30000
        self.after(gap, self._retry_menu)

    def _clear_hint(self, _e=None):
        if self.entry.get() == "Ask anything...":
            self.entry.delete(0, "end")

    def refresh(self, keep_on_empty=True):
        cur = self.combo.get()
        found: dict[str, int] = {}
        for hwnd, title in list_windows():
            label = title if len(title) <= 60 else title[:57] + "..."
            if label not in found:
                found[label] = hwnd
        if not found and keep_on_empty and self._hwnds:
            return len(self._hwnds)  # blind window: keep the good menu
        self._hwnds = found
        self.combo["values"] = []
        for label in found:
            self.combo["values"] = (*self.combo["values"], label)
        if cur in self._hwnds:
            self.combo.set(cur)
            self._hwnd = self._hwnds[cur]
        elif self.combo["values"]:
            self.combo.current(0)
            self._on_pick()
        else:
            self._hwnd = 0
        self._set_status("%d apps found." % len(self._hwnds)
                        if self._hwnds else
                        "Menu blocked here - use Read-fg or Refresh")
        return len(self._hwnds)

    def _on_pick(self, _e=None):
        self._hwnd = self._hwnds.get(self.combo.get(), 0)

    def _say(self, text: str, role: str):
        self.chat["state"] = "normal"
        for line in shape_for_rich(text).split("\n"):
            tags = [role] + (["right"] if is_rtl(line) else [])
            self.chat.insert("end", line + "\n", tuple(tags))
        self.chat.insert("end", "\n")
        self.chat["state"] = "disabled"
        self.chat.see("end")

    def _set_status(self, text: str):
        self.status["text"] = text

    def do_read(self):
        if not self._hwnd:
            self._set_status("Pick an app first.")
            return
        self._set_status("Thinking...")
        threading.Thread(target=self._read_job,
                         args=(self._hwnd,), daemon=True).start()

    def _note_error(self, where: str, e: BaseException) -> None:
        # File write is thread-safe; the status line goes through the
        # queue so only the main thread touches Tk widgets.
        log_error(where, e)
        try:
            n = error_count()
        except Exception:
            n = 0
        self._jobs.put(("status", "Error logged (%d) - see errors.log" % n,
                        [], ""))

    def report_callback_exception(self, exc, val, tb):
        import sys as _sys
        self._note_error("tk-callback", val)
        _sys.__excepthook__(exc, val, tb)

    def _on_uncaught(self, exc, val, tb):
        import sys as _sys
        self._note_error("uncaught", val)
        _sys.__excepthook__(exc, val, tb)

    def _read_job(self, hwnd: int):
        try:
            lines = read_window(hwnd)
            body = "\n".join("- [%.0f%%] %s" % (c, t) for t, c in lines)
            self._jobs.put(("read", body or "No text found.", lines, ""))
        except Exception as e:
            self._note_error("read", e)
            self._jobs.put(("read", "Error: %s" % e, [], ""))

    def do_read_fg(self):
        """Countdown, then read whatever window is foreground (no menu)."""
        self._set_status("Click the target app - reading in 3s...")
        threading.Thread(target=self._fg_job, daemon=True).start()

    def _fg_job(self):
        import time
        for i in (3, 2, 1):
            self._jobs.put(("status", "Reading in %d - click the app!" % i,
                            [], ""))
            time.sleep(1)
        hwnd = foreground_window()
        if not hwnd or window_region(hwnd) is None:
            self._jobs.put(("read", "No foreground window found.", [], ""))
            return
        try:
            lines = read_window(hwnd)
            body = "\n".join("- [%.0f%%] %s" % (c, t) for t, c in lines)
            self._jobs.put(("read", body or "No text found.", lines, ""))
        except Exception as e:
            self._note_error("read-fg", e)
            self._jobs.put(("read", "Error: %s" % e, [], ""))

    def do_ask(self):
        q = self.entry.get().strip()
        if not q or q == "Ask anything...":
            return
        self.entry.delete(0, "end")
        self._say(q, "user")
        if not self._last_ocr and not self._hwnd:
            self._say("Pick an app and press Read screen first.", "meta")
            return
        self._set_status("Thinking...")
        threading.Thread(target=self._ask_job, args=(q,), daemon=True).start()

    def _ask_job(self, q: str):
        try:
            ocr = self._last_ocr or read_window(self._hwnd)
            self._jobs.put(("ask", ask_brain(q, ocr), ocr, ""))
        except Exception as e:
            self._note_error("ask", e)
            self._jobs.put(("ask", "Error: %s" % e, self._last_ocr, ""))

    def _poll(self):
        try:
            while True:
                kind, text, lines, _ = self._jobs.get_nowait()
                if kind == "status":
                    self._set_status(text)
                    continue
                if kind == "read" and lines:
                    self._last_ocr = lines
                    pill = screen_label(len(lines))
                    self.pill["text"] = ("Attached: " + pill) if pill else ""
                self._say(text, "ai")
                self._set_status("Ready.")
        except Exception:
            pass
        finally:
            self.after(200, self._poll)


def main() -> int:
    Eye().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
