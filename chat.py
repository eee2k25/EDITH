import os
import sys
import json
import re
import time
import shutil
import datetime
import threading
import subprocess

import requests
from dotenv import load_dotenv

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except ImportError:
    pyautogui = None

try:
    import win32gui, win32con, win32api, win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

try:
    import pyttsx3
    HAS_TTS = True
except ImportError:
    HAS_TTS = False

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False

try:
    import serial
    from serial.tools import list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

try:
    import win32com.client
    HAS_COM = True
except ImportError:
    HAS_COM = False

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()
API_KEY = os.getenv("JARVIS_LLM_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

LLM_TIMEOUT = 30
LLM_MAX_TOKENS = 1500
MODEL_FETCH_TIMEOUT = 10
CONTEXT_MSG_CAP = 30
FILE_READ_CAP = 10000
TOOL_OUTPUT_CAP = 6000

WORKSPACE_DIR = r"C:\WINDOWS\system32\JARVIS-making"
BACKUP_DIR = os.path.join(WORKSPACE_DIR, "backups")
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "jarvis_memory.json")
MODEL_CACHE_FILE = os.path.join(MEMORY_DIR, "free_models_cache.json")
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

print("=" * 55)
print("    J.A.R.V.I.S. - AUTONOMOUS CORE v3.2 (FREE MODELS)")
print("=" * 55)

if not API_KEY:
    print("[WARN] JARVIS_LLM_API_KEY not found in .env — LLM calls will fail.")

CURATED_FREE_MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-31b-it:free",
    "cohere/north-mini-code:free",
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nex-agi/nex-n2.5-pro:free",
    "poolside/laguna-s-2.1:free",
    "google/gemma-4-26b-a4b-it:free",
    "poolside/laguna-xs-2.1:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "thinkingmachines/inkling:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openrouter/free",
]

MODEL_CACHE_TTL = 24 * 3600
model_queue = list(CURATED_FREE_MODELS)
model_cooldown = {}
preferred_model = None

def fetch_free_models():
    try:
        r = requests.get(OPENROUTER_MODELS_URL, timeout=MODEL_FETCH_TIMEOUT)
        r.raise_for_status()
        free = []
        for m in r.json().get("data", []):
            mid = m.get("id", "")
            if not (mid.endswith(":free") or mid == "openrouter/free"):
                continue
            arch = m.get("architecture") or {}
            mod = str(arch.get("modality", "")) + str(arch.get("input_modalities", ""))
            if "text" not in mod.lower():
                continue
            free.append({
                "id": mid,
                "context_length": m.get("context_length") or 0,
                "name": m.get("name", ""),
            })
        free.sort(key=lambda x: -x["context_length"])
        return free
    except Exception:
        return []

def _apply_models(live_models, save_cache=False):
    global model_queue
    if not live_models:
        return
    live_ids = {m["id"] for m in live_models}
    ordered = [m for m in CURATED_FREE_MODELS if m in live_ids]
    for m in live_models:
        if m["id"] not in ordered:
            ordered.append(m["id"])
    if ordered:
        model_queue = ordered
    if save_cache:
        try:
            with open(MODEL_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"fetched": time.time(), "models": live_models}, f, indent=2)
        except Exception:
            pass

def _background_refresh():
    _apply_models(fetch_free_models(), save_cache=True)

def build_model_queue(force_refresh=False):
    global model_queue
    cached = None
    if not force_refresh and os.path.exists(MODEL_CACHE_FILE):
        try:
            with open(MODEL_CACHE_FILE, encoding="utf-8") as f:
                blob = json.load(f)
            if time.time() - blob.get("fetched", 0) < MODEL_CACHE_TTL:
                cached = blob.get("models") or []
        except Exception:
            cached = None

    if cached:
        _apply_models(cached)
    elif force_refresh:
        _apply_models(fetch_free_models(), save_cache=True)
    else:
        model_queue = list(CURATED_FREE_MODELS)
        threading.Thread(target=_background_refresh, daemon=True).start()

    print("[MODELS] Free model queue (fast first):")
    for i, mid in enumerate(model_queue[:8]):
        print(f"    {i + 1}. {mid}")
    return model_queue

def _cooldown(model, secs):
    model_cooldown[model] = time.time() + secs

def _extract_json(raw):
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    return None

def _repair_json(bad_raw, model):
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a JSON fixer. Output ONLY a valid JSON object, nothing else."},
                {"role": "user", "content": "Rewrite the following as valid JSON only:\n\n" + bad_raw[:2000]},
            ],
        }
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=LLM_TIMEOUT)
        if r.status_code == 200:
            fixed = r.json()["choices"][0]["message"]["content"]
            return _extract_json(fixed)
    except Exception:
        pass
    return None

def llm_call(messages):
    global preferred_model
    if not API_KEY:
        return None, "API key missing"

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    last_error = "unknown"

    ordered = []
    if preferred_model and preferred_model in model_queue:
        ordered.append(preferred_model)
    for m in model_queue:
        if m not in ordered:
            ordered.append(m)

    for model in ordered:
        if model_cooldown.get(model, 0) > time.time():
            continue

        payload = {
            "model": model,
            "messages": messages[-CONTEXT_MSG_CAP:],
            "response_format": {"type": "json_object"},
            "max_tokens": LLM_MAX_TOKENS,
        }
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=LLM_TIMEOUT)
            if resp.status_code == 400 and "response_format" in (resp.text or ""):
                payload.pop("response_format", None)
                resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=LLM_TIMEOUT)

            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                cmd = _extract_json(raw)
                if cmd is not None:
                    preferred_model = model
                    return cmd, model
                repaired = _repair_json(raw, model)
                if repaired is not None:
                    preferred_model = model
                    return repaired, model
                _cooldown(model, 60)
                continue

            if resp.status_code in (401, 403):
                return None, f"API key rejected ({resp.status_code})"

            _cooldown(model, 60)
        except Exception:
            _cooldown(model, 30)

    return None, last_error

system_prompt = """
You are J.A.R.V.I.S., an advanced autonomous engineering assistant.
Your operator is Mekala Ganesh. When the user asks to perform an action (like opening an app, running a command, reading a file), you MUST return a valid JSON object specifying the action. If it is just conversation, use "chat_only".

You must respond ONLY in strict JSON format:
{
    "action": "chat_only | read_file | write_file | git_sync | run_script | run_powershell | type_in_window | read_screen | speak | listen | matlab | arduino_ports | arduino_read",
    "filename": "",
    "content": "",
    "commit_msg": "",
    "command": "",
    "window_name": "",
    "text": "",
    "speech": "Your vocal or text conversational response."
}
"""

messages = [{"role": "system", "content": system_prompt}]

if os.path.exists(MEMORY_FILE):
    prev = load_memory() if 'load_memory' in globals() else []
    # simple local fallback
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = []
    if prev:
        try:
            ans = input(f"\n[MEMORY] Found {len(prev)} messages. Load? (yes/no): ").strip().lower()
        except Exception:
            ans = "no"
        if ans == "yes":
            messages = prev
            messages[0] = {"role": "system", "content": system_prompt}

build_model_queue()

try:
    while True:
        try:
            user_cmd = input("\nJ.A.R.V.I.S.> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nShutting down...")
            break

        if not user_cmd:
            continue

        low = user_cmd.lower()
        if low in ['exit', 'quit', 'close']:
            break
        if low == 'models':
            for i, mid in enumerate(model_queue):
                print(f"    {i + 1}. {mid}")
            continue
        if low == 'clear memory':
            messages = [{"role": "system", "content": system_prompt}]
            print("[MEMORY] Cleared.")
            continue

        messages.append({"role": "user", "content": user_cmd})

        command, model = llm_call(messages)
        if command is None:
            print(f"[LLM] All free models unreachable ({model}).")
            # Fallback to direct conversational response if LLM completely fails
            print(f"\n[J.A.R.V.I.S.]: I'm having trouble reaching the model endpoint right now, Mekala. Let's try again in a moment.")
            continue

        messages.append({"role": "assistant", "content": json.dumps(command, ensure_ascii=False)})
        print(f"[LLM] {model}")

        if "speech" in command and command["speech"]:
            print(f"\n[J.A.R.V.I.S.]: {command['speech']}\n")

        action = command.get("action")
        tool_output = ""

        if action == "run_powershell" or action == "run_script":
            cmd = command.get("command") or f"python {command.get('filename', '')}"
            try:
                res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
                tool_output = f"Output:\n{res.stdout}\nErrors:\n{res.stderr}"
            except Exception as e:
                tool_output = str(e)
            print(tool_output)
        elif action == "chat_only":
            pass
        else:
            print(f"[ACTION] Executed action: {action}")

        # Save state
        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

except KeyboardInterrupt:
    print("\nShutting down...")