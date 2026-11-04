# Bridge — Arabic Eye Tool <> Muse leader body

- This project is a separate body at `E:\Smart tools\Arabic Eye Tool`: local Arabic screen reader (mss + indra-ocr/Tesseract + fixer + Rich/tkinter + Qwen2.5-0.5B brain).
- Leader body: `E:\Agents\Agent-Muse` (Mind `E:\Agents\Agent-Muse\mind`, Muscle `E:\Agents\Agent-Muse\muscle`).
- Relation: Muse works here as surgeon — edits only this project's files, imports no Muscle engines into it. Only DB + memory records return to the leader.
- Canonical stores: leader DB `E:\Agents\Agent-Muse\muscle\databases\muse.sqlite` (project `arabic-eye-tool`), leader memory (project scope).
- Trust: workspace trusted; AGENTS.md + `.agents/skills/` + `.agents/memory/` load automatically.
- Standing user laws apply here too: NO-INSTALL without explicit order, Ollama forbidden in this tool, run.bat is the only launcher.
