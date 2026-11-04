# AGENTS.md

Muse Code reads this file as project rules when it runs in this directory.

## Project

- Name: Arabic Eye Tool — الشاهد 👁️ (local Arabic screen reader, Windows 11, Python)
- Pipeline (all local, no cloud): mss screenshot (Pillow fallback) -> sandra_capture.png -> indra-ocr (Tesseract fallback) -> fixer.smart_fix_line -> arabic-reshaper + python-bidi -> Rich chat / tkinter desktop
- Brain: Qwen2.5-0.5B in-process (local safetensors) + LM Studio fallback lfm3-1.7b. Ollama is forbidden here and is never touched.
- Launcher: double-click `run.bat` (the ONLY launcher, runs app\desktop_eye.py with pythonw). No console needed.

## Common Commands

- `python app/terminal_reader.py` — interactive Rich chat (Enter or `s` reads screen, `clear` clears, `logical` toggles shaping, `q` quits)
- `python app/terminal_reader.py --once` — single read + response card
- `python app/terminal_reader.py --region X Y W H` — capture a region
- `python app/terminal_reader.py --logical` — no reshaping (for Windows Terminal which shapes Arabic natively)
- `python app/test_fixer.py` — fixer regression test
- `pip install -r requirements.txt` — installs Pillow, pytesseract, arabic-reshaper, python-bidi, indra-ocr, numpy, mss, rich (needs explicit order per NO-INSTALL)

## Project Layout

- `app/terminal_reader.py` — Rich chat TUI + brain wiring
- `app/desktop_eye.py` — tkinter desktop app (window, app menu, chat)
- `app/ocr_engine.py` — capture (mss/Pillow) + OCR (indra-ocr/Tesseract)
- `app/fixer.py` — Arabic visual-to-logical order fixer
- `app/error_log.py` — error logging helper
- `app/test_fixer.py` — fixer tests
- `run.bat` — the ONLY launcher
- `requirements.txt` — pinned local deps
- `README.md` — Arabic usage guide (source of truth for behavior)

## Bridge (Muse leader body)

- Leader body: `E:\Agents\Agent-Muse` (Mind: `E:\Agents\Agent-Muse\mind`, Muscle: `E:\Agents\Agent-Muse\muscle`)
- Project skills load from: `.agents/skills/` (Meta loads project skills only from there)
- Project memory: `.agents/memory/MEMORY.md` (index) + topic files (e.g. `bridge.md`)
- Surgeon rule: when Muse is summoned inside this folder, it edits only this project's files and imports none of its Muscle into it. Only database + memory records return to the leader body.
- Trust note: this workspace is trusted — project rules/skills/memory load on launch.
