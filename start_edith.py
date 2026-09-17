"""EDITH / JARVIS first-run launcher.
Asks for an OpenRouter key if missing, saves it to local .env, then starts chat.py.
Never commit .env.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

ENV_FILE = ROOT / ".env"
KEY_NAME = "JARVIS_LLM_API_KEY"
CHAT = ROOT / "chat.py"
OPENROUTER_KEYS = "https://openrouter.ai/keys"

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
    except Exception:
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def _key_ok(k: str | None) -> bool:
    if not k:
        return False
    k = k.strip().strip('"').strip("'")
    return k.startswith("sk-or-") and len(k) > 20

def _upsert_env(api_key: str) -> None:
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()

    def set_or_add(name: str, value: str) -> None:
        nonlocal lines
        out, found = [], False
        for line in lines:
            if line.strip().startswith(name + "="):
                out.append(f"{name}={value}")
                found = True
            else:
                out.append(line)
        if not found:
            if out and out[-1].strip():
                out.append("")
            out.append(f"{name}={value}")
        lines = out

    set_or_add("JARVIS_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    set_or_add(KEY_NAME, api_key)
    ENV_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

def ask_for_key() -> str:
    print("=" * 60)
    print("  EDITH / J.A.R.V.I.S.  —  first-time setup")
    print("=" * 60)
    print()
    print("  This app needs a FREE OpenRouter API key (yours, not shared).")
    print()
    print("  How to get one (2 minutes):")
    print("    1. Open  " + OPENROUTER_KEYS)
    print("    2. Sign in with Google / GitHub / email")
    print("    3. Click Create API Key")
    print("    4. Copy the key  (starts with sk-or-v1- ...)")
    print()
    print("  The key is saved only on THIS computer in .env")
    print("  It is never uploaded to GitHub.")
    print()
    try:
        import webbrowser
        webbrowser.open(OPENROUTER_KEYS)
        print("  (Opened the key page in your browser.)")
        print()
    except Exception:
        pass

    while True:
        try:
            key = input("  Paste your OpenRouter key here, then Enter:\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(1)
        key = key.strip().strip('"').strip("'")
        if _key_ok(key):
            _upsert_env(key)
            os.environ[KEY_NAME] = key
            print()
            print("  Key saved. Starting JARVIS...")
            print()
            return key
        print()
        print("  That does not look like an OpenRouter key.")
        print("  It should start with sk-or-v1- and be a long string.")
        print("  Get one at " + OPENROUTER_KEYS)
        print()

def main() -> None:
    if not CHAT.exists():
        print("chat.py not found in", ROOT)
        print("Extract the full EDITH folder and run this from inside it.")
        input("Press Enter to exit...")
        sys.exit(1)

    _load_env()
    key = os.getenv(KEY_NAME, "")
    if not _key_ok(key):
        ask_for_key()

    runpy.run_path(str(CHAT), run_name="__main__")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")