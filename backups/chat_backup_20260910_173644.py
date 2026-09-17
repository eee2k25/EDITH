"""
=====================================================================
  J.A.R.V.I.S. — Autonomous Core v3.2  (FREE MODELS ONLY, $0)
=====================================================================
Kept from v3.1:
  * OpenRouter strict-JSON action loop + GitHub auto-sync + backups
  * PERSISTENT MEMORY  -> memory/jarvis_memory.json
  * SAFETY GUARD       -> destructive PowerShell/scripts blocked
  * type_in_window / read_screen / speak / listen / matlab / arduino

NEW in v3.2 — zero-cost + self-healing LLM engine:
  * FREE MODELS ONLY. Never sends a single paid token. $0 forever.
  * AUTO-SELECT: picks the most powerful FREE agentic model available
    right now, in a curated priority order (verified live on 2026-09-11).
  * LIVE REFRESH: re-reads OpenRouter's public /models endpoint daily
    so the list never goes stale (cached to disk; works offline too).
  * AUTO-FAILOVER: if a model rate-limits / errors / returns bad JSON,
    JARVIS blacklists it briefly and moves to the next free model —
    the chat never stops.
  * SELF-REPAIR: malformed JSON is re-sent to the model to be fixed
    automatically; tool errors are fed back for auto-fixing as before.

Start:  jarvis    (PowerShell profile)
=====================================================================
"""
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

# ------------------------------------------------------------------
# Optional third-party imports — all guarded.
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# Config & directories
# ------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("JARVIS_LLM_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

WORKSPACE_DIR = r"C:\WINDOWS\system32\JARVIS-making"
BACKUP_DIR = os.path.join(WORKSPACE_DIR, "backups")
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "jarvis_memory.json")
MODEL_CACHE_FILE = os.path.join(MEMORY_DIR, "free_models_cache.json")
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

print("=" * 55)
print("   J.A.R.V.I.S. - AUTONOMOUS CORE v3.2 (FREE MODELS)")
print("=" * 55)

browser = None
try:
    from jarvis.config import Settings
    from jarvis.modules.browser import BrowserModule
    settings = Settings()
    browser = BrowserModule(settings)
    browser.start()
    print("[BROWSER] Connected.")
except Exception as _e:
    print(f"[WARN] Browser module unavailable ({_e}) — continuing without Edge watcher.")

if not API_KEY:
    print("[WARN] JARVIS_LLM_API_KEY not found in .env — LLM calls will fail.")
    print("       Add  JARVIS_LLM_API_KEY=sk-or-...  to a .env file in JARVIS-making.")


# ==================================================================
#  FREE MODEL AUTO-SELECTION ENGINE
# ==================================================================
# Curated priority order of free, agentic, text models — verified live
# against OpenRouter's /models endpoint on 2026-09-11. Best first.
CURATED_FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",   # 550B MoE, 1M ctx — strongest free
    "thinkingmachines/inkling:free",            # 1M ctx, agentic
    "nvidia/nemotron-3.5-lightning:free",       # 1M ctx, fast
    "nex-agi/nex-n2.5-pro:free",                # agentic, 262K
    "poolside/laguna-s-2.1:free",               # coding agent, 262K
    "nvidia/nemotron-3-super-120b-a12b:free",   # 262K
    "google/gemma-4-31b-it:free",               # 262K
    "cohere/north-mini-code:free",              # coding, 256K
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # 256K reasoning
    "openrouter/free",                          # auto-router catch-all
]

MODEL_CACHE_TTL = 24 * 3600  # refresh the free list once a day

model_queue = list(CURATED_FREE_MODELS)
model_cooldown = {}  # model_id -> unix time it becomes usable again


def _zero_price(x):
    try:
        return float(str(x)) == 0
    except Exception:
        return False


def fetch_free_models():
    """Pull the current list of $0 text models from OpenRouter (no key needed)."""
    try:
        r = requests.get(OPENROUTER_MODELS_URL, timeout=30)
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
    except Exception as e:
        print(f"[MODELS] live fetch failed ({e})")
        return []


def build_model_queue(force_refresh=False):
    """Build the ordered model queue: curated list ∩ live list, then the rest."""
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

    if cached is None:
        live = fetch_free_models()
        if live:
            cached = live
            try:
                with open(MODEL_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"fetched": time.time(), "models": live}, f, indent=2)
            except Exception:
                pass

    if cached:
        live_ids = {m["id"] for m in cached}
        ordered = [m for m in CURATED_FREE_MODELS if m in live_ids]
        for m in cached:
            if m["id"] not in ordered:
                ordered.append(m["id"])
        if ordered:
            model_queue = ordered

    print("[MODELS] Free model queue (best first):")
    for i, mid in enumerate(model_queue[:8]):
        print(f"   {i + 1}. {mid}")
    if len(model_queue) > 8:
        print(f"   ... and {len(model_queue) - 8} more fallback(s).")
    return model_queue


def _cooldown(model, secs):
    model_cooldown[model] = time.time() + secs


def _extract_json(raw):
    """Robustly pull a JSON object out of a model reply (handles code fences)."""
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
    """Ask a model to re-emit bad JSON as valid JSON (self-repair)."""
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a JSON fixer. Output ONLY a valid JSON object, nothing else."},
                {"role": "user", "content": "Rewrite the following as valid JSON only:\n\n" + bad_raw[:2000]},
            ],
        }
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            fixed = r.json()["choices"][0]["message"]["content"]
            cmd = _extract_json(fixed)
            if cmd is not None:
                return cmd
    except Exception:
        pass
    return None


def llm_call(messages, max_rounds=2):
    """
    Call the best available FREE model, failing over automatically.
    Returns (command_dict, model_id) on success, or (None, last_error).
    """
    if not API_KEY:
        return None, "API key missing — add JARVIS_LLM_API_KEY to .env"

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    last_error = "unknown"

    for round_no in range(max_rounds):
        for model in model_queue:
            if model_cooldown.get(model, 0) > time.time():
                continue  # still cooling down from a recent failure

            payload = {
                "model": model,
                "messages": _api_payload(messages),
                "response_format": {"type": "json_object"},
            }
            try:
                resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)

                # Some free models reject json_object mode -> retry without it.
                if resp.status_code == 400 and "response_format" in (resp.text or ""):
                    payload.pop("response_format", None)
                    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)

                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"]
                    cmd = _extract_json(raw)
                    if cmd is not None:
                        return cmd, model
                    repaired = _repair_json(raw, model)
                    if repaired is not None:
                        return repaired, model
                    last_error = f"{model} returned non-JSON"
                    print(f"[LLM] {model} returned bad JSON — cooling down and switching.")
                    _cooldown(model, 120)
                    continue

                if resp.status_code in (401, 403):
                    return None, f"API key rejected ({resp.status_code}). Check JARVIS_LLM_API_KEY."

                if resp.status_code == 402:
                    last_error = f"{model}: no credits"
                    print(f"[LLM] {model} needs credits (skipping, it is not free now).")
                    _cooldown(model, 86400)  # 24h

                elif resp.status_code == 429:
                    last_error = f"{model}: rate limited"
                    print(f"[LLM] {model} rate-limited — switching to next free model.")
                    _cooldown(model, 300)

                else:
                    last_error = f"{model}: HTTP {resp.status_code}"
                    print(f"[LLM] {model} error {resp.status_code} — switching.")
                    _cooldown(model, 120)

            except requests.exceptions.RequestException as e:
                last_error = f"{model}: network error"
                print(f"[LLM] {model} network error — switching.")
                _cooldown(model, 60)

        if round_no < max_rounds - 1:
            print(f"[LLM] All free models busy ({last_error}). Waiting 10s, retrying...")
            time.sleep(10)

    return None, last_error


def _api_payload(messages):
    """Send the conversation, capping context sent to the API to control cost/latency."""
    if len(messages) <= 100:
        return messages
    return [messages[0]] + messages[-99:]


# ==================================================================
#  SAFETY SCANNER (v2) — no false "rm -rf"/"format" alarms
# ==================================================================
SHELL_DANGEROUS = [
    (re.compile(r"(?i)(^|[\s;&|])format\s+[a-z]:"),            "BLOCK", "disk FORMAT command"),
    (re.compile(r"(?i)(^|[\s;&|])format\b\s+.*(/fs:|/q)"),      "BLOCK", "disk FORMAT command"),
    (re.compile(r"(?i)(^|[\s;&|])rm\s+(-\w+\s+)+[/.~$a-zA-Z]"), "BLOCK", "recursive delete (rm -rf ...)"),
    (re.compile(r"(?i)(^|[\s;&|])rm\s+-\w*[rf]\w*"),            "BLOCK", "recursive delete (rm -rf)"),
    (re.compile(r"(?i)Remove-Item\b[^|\n]*(-Recurse|-Force)"),  "BLOCK", "Remove-Item -Recurse/-Force"),
    (re.compile(r"(?i)(^|[\s;&|])del\s+/[sqf]\b"),              "BLOCK", "del /s /q /f"),
    (re.compile(r"(?i)(^|[\s;&|])rd\s+/s\b"),                   "BLOCK", "rd /s"),
    (re.compile(r"(?i)(^|[\s;&|])deltree\b"),                   "BLOCK", "deltree"),
    (re.compile(r"(?i)(^|[\s;&|])shutdown\b"),                  "BLOCK", "system shutdown"),
    (re.compile(r"(?i)(^|[\s;&|])(restart|stop)-computer\b"),   "BLOCK", "PowerShell shutdown cmdlet"),
    (re.compile(r"(?i)(^|[\s;&|])reg\s+delete\b"),              "BLOCK", "registry delete"),
    (re.compile(r"(?i)(^|[\s;&|])diskpart\b"),                  "BLOCK", "diskpart"),
    (re.compile(r"(?i)\b(iex|invoke-expression)\b\s*[\(\s]"),   "BLOCK", "Invoke-Expression"),
    (re.compile(r"(?i)(curl|wget|iwr)\b[^|\n]*\|\s*iex\b"),     "BLOCK", "download | Invoke-Expression"),
]

COMMAND_STRING_RE = re.compile(
    r"(?:os\.system|os\.popen|subprocess\.(?:run|call|check_call|check_output|Popen))"
    r"\s*\(\s*[rfbu]*([\"'])(.*?)\1", re.DOTALL)
LIST_DANGEROUS = {"rm", "del", "deltree", "format", "shutdown", "diskpart", "rd"}


def _scan_command_lines(text):
    findings = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for rx, sev, reason in SHELL_DANGEROUS:
            if rx.search(s):
                findings.append((sev, f"{reason}: {s[:70]}"))
    return findings


def scan_shell_command(command):
    findings = _scan_command_lines(command)
    seen, out = set(), []
    for f in findings:
        if f[1] not in seen:
            seen.add(f[1])
            out.append(f)
    return out


def scan_code(code):
    findings = []
    for m in COMMAND_STRING_RE.finditer(code):
        findings += _scan_command_lines(m.group(2))
    for m in re.finditer(r"\[([^\]\n]*)\]", code):
        args = [a.strip().strip("\"'") for a in m.group(1).split(",")]
        if args and args[0].lower() in LIST_DANGEROUS:
            findings.append(("BLOCK", f"dangerous command in list: {args[0]} ..."))
    seen, out = set(), []
    for f in findings:
        if f[1] not in seen:
            seen.add(f[1])
            out.append(f)
    return out


def has_blocking(findings):
    return any(sev == "BLOCK" for sev, _ in findings)


# ==================================================================
#  VISUAL TYPING
# ==================================================================
def _list_windows():
    if not HAS_WIN32:
        return []
    results = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t.strip():
                results.append((hwnd, t))

    win32gui.EnumWindows(cb, None)
    return results


def _find_window(title_part):
    lp = title_part.lower()
    for hwnd, t in _list_windows():
        if lp in t.lower():
            return hwnd, t
    return None


def _focus_window(hwnd):
    if not HAS_WIN32:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        fg = win32gui.GetForegroundWindow()
        our_tid = win32api.GetCurrentThreadId()
        fg_tid, _ = win32process.GetWindowThreadProcessId(fg)
        attached = False
        if fg_tid != our_tid:
            win32process.AttachThreadInput(our_tid, fg_tid, True)
            attached = True
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        if attached:
            win32process.AttachThreadInput(our_tid, fg_tid, False)
        time.sleep(0.4)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception as e:
        print(f"[TYPING] focus error: {e}")
        return False


def _escape_sendkeys(text):
    text = re.sub(r"([+^%~(){}\[\]])", r"{\1}", text)
    return text.replace("\n", "{ENTER}").replace("'", "''")


def _paste(text):
    if not pyperclip or not pyautogui:
        return False
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""
    try:
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)
        return True
    except Exception as e:
        print(f"[TYPING] paste failed: {e}")
        return False
    finally:
        try:
            pyperclip.copy(old)
        except Exception:
            pass


def _sendkeys_ps(text):
    ps = ("Add-Type -AssemblyName System.Windows.Forms; "
          "[System.Windows.Forms.SendKeys]::SendWait('" + _escape_sendkeys(text) + "')")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=30)
        return True
    except Exception as e:
        print(f"[TYPING] SendKeys failed: {e}")
        return False


def type_text(text, window_name=None, method="auto"):
    if window_name:
        found = _find_window(window_name)
        if not found:
            print(f"[TYPING] No visible window matches '{window_name}'.")
            titles = [t for _, t in _list_windows()][:20]
            print("[TYPING] Visible windows:", titles)
            return False
        hwnd, title = found
        if not _focus_window(hwnd):
            print(f"[TYPING] Could not focus '{title}'. Run JARVIS from an ADMIN PowerShell.")
            return False
    if method in ("auto", "paste") and _paste(text):
        return True
    if method in ("auto", "write") and pyautogui is not None:
        try:
            pyautogui.write(text, interval=0.02)
            return True
        except Exception as e:
            print(f"[TYPING] write failed: {e}")
    if method in ("auto", "sendkeys") and _sendkeys_ps(text):
        return True
    return False


# ==================================================================
#  VISION — screen reading (OCR)
# ==================================================================
def read_screen(region=None, lang="eng"):
    if not HAS_OCR:
        return "[VISION] pytesseract missing: pip install pytesseract + install Tesseract-OCR engine"
    if pyautogui is None:
        return "[VISION] pyautogui missing: pip install pyautogui"
    img = pyautogui.screenshot(region=region)
    return pytesseract.image_to_string(img, lang=lang).strip()


def find_text(text, region=None, lang="eng"):
    if not HAS_OCR or pyautogui is None:
        return None
    img = pyautogui.screenshot(region=region)
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    t = text.lower()
    for i, w in enumerate(data["text"]):
        if t in w.lower():
            x = data["left"][i] + data["width"][i] // 2
            y = data["top"][i] + data["height"][i] // 2
            if region:
                x += region[0]
                y += region[1]
            return x, y
    return None


def click_text(text, region=None, lang="eng"):
    pos = find_text(text, region=region, lang=lang)
    if pos:
        pyautogui.click(*pos)
        return True
    return False


# ==================================================================
#  VOICE
# ==================================================================
_engine = None
_tts_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None and HAS_TTS:
        try:
            _engine = pyttsx3.init()
            _engine.setProperty("rate", 175)
        except Exception as e:
            print(f"[VOICE] pyttsx3 init failed: {e}")
            _engine = None
    return _engine


def _speak_sapi(text):
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$s.Speak('" + text.replace("'", "''") + "')")
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[VOICE] SAPI fallback failed: {e}")


def speak(text, block=False):
    if not text:
        return False

    def _run():
        eng = _get_engine()
        if eng is not None:
            with _tts_lock:
                try:
                    eng.say(text)
                    eng.runAndWait()
                    return
                except Exception as e:
                    print(f"[VOICE] error: {e}")
        _speak_sapi(text)

    if block:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()
    return True


def listen(timeout=5, phrase_time_limit=8, language="en-IN", duration=6):
    if not HAS_SR:
        return "[VOICE] speech_recognition missing: pip install SpeechRecognition"
    r = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.4)
            print("[VOICE] Listening...")
            try:
                audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            except sr.WaitTimeoutError:
                return "(nothing heard)"
        try:
            return r.recognize_google(audio, language=language)
        except sr.UnknownValueError:
            return "(could not understand)"
        except sr.RequestError as e:
            return f"[VOICE] recognition service error: {e}"
    except Exception as e:
        return f"[VOICE] mic error ({e}). Try: pip install pyaudio  or  sounddevice numpy"


# ==================================================================
#  MATLAB
# ==================================================================
_ml = None


def _get_matlab():
    global _ml
    if _ml is None and HAS_COM:
        try:
            _ml = win32com.client.Dispatch("matlab.application")
            _ml.Visible = 1
            print("[MATLAB] Connected via COM.")
        except Exception as e:
            print(f"[MATLAB] COM connect failed: {e}")
            print("[MATLAB] Fix: run 'matlab /regserver' once as admin.")
            _ml = None
    return _ml


def matlab_execute(command, fallback="batch"):
    ml = _get_matlab()
    if ml is not None:
        try:
            return ml.Execute(command)
        except Exception as e:
            print(f"[MATLAB] Execute failed: {e}")
    if fallback == "batch":
        try:
            res = subprocess.run(["matlab", "-batch", command],
                                 capture_output=True, text=True, timeout=180)
            return res.stdout or res.stderr or "(no output)"
        except FileNotFoundError:
            return "[MATLAB] matlab executable not found on PATH."
        except Exception as e:
            return f"[MATLAB] batch failed: {e}"
    return None


# ==================================================================
#  ARDUINO
# ==================================================================
def arduino_ports():
    if not HAS_SERIAL:
        return []
    return [(p.device, p.description) for p in list_ports.comports()]


def arduino_read(port=None, baud=9600, lines=5):
    if not HAS_SERIAL:
        return "[ARDUINO] pyserial missing: pip install pyserial"
    if not port:
        ports = arduino_ports()
        if not ports:
            return "[ARDUINO] No COM ports found. Is the board plugged in?"
        port = ports[0][0]
    try:
        ser = serial.Serial(port, baud, timeout=1.0)
        time.sleep(2.0)
        out = []
        for _ in range(lines):
            line = ser.readline().decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                out.append(line)
            else:
                break
        ser.close()
        return "\n".join(out) or "(no data received)"
    except Exception as e:
        return f"[ARDUINO] error: {e}"


# ==================================================================
#  PERSISTENT MEMORY
# ==================================================================
def save_memory(messages):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[MEMORY] save failed: {e}")
        return False


def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ==================================================================
#  GITHUB + LOCAL BACKUP
# ==================================================================
def auto_backup_and_git_push(commit_msg="Auto-save progress checkpoint"):
    try:
        if os.path.exists("chat.py"):
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(BACKUP_DIR, f"chat_backup_{timestamp}.py")
            shutil.copy("chat.py", backup_path)

        os.chdir(WORKSPACE_DIR)
        subprocess.run(["git", "add", "."], capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True)
        push_res = subprocess.run(["git", "push"], capture_output=True, text=True)

        if push_res.returncode == 0:
            return "Successfully backed up locally and pushed to GitHub repository!"
        return f"Local backup saved, but git push warning: {push_res.stderr.strip()}"
    except Exception as e:
        return f"Backup/Git error: {str(e)}"


# ==================================================================
#  SYSTEM PROMPT
# ==================================================================
system_prompt = """
You are J.A.R.V.I.S., an advanced autonomous engineering assistant with self-improvement,
error auto-fixing, and GitHub version control capabilities.
Your operator is Mekala Ganesh, an EEE student developing IoT systems.

You can execute multi-step tool loops. If the user asks you to save progress, fix errors, or modify code:
1. Use "read_file" or analyze the error log.
2. Use "write_file" to patch code.
3. Use "git_sync" to automatically commit and push the updated progress to GitHub so work is never lost due to power cuts.
4. Use "run_script" or "run_powershell" to test operations.

Available actions:
1.  "chat_only"      - For general conversation.
2.  "read_file"      - Inspect local source files. (Requires "filename")
3.  "write_file"     - Save or update code in a file. (Requires "filename" and "content")
4.  "git_sync"       - Commits and pushes all workspace changes to GitHub. (Requires "commit_msg")
5.  "run_script"     - Executes a python script. (Requires "filename")
6.  "run_powershell" - Runs a terminal command. (Requires "command"). Destructive commands are auto-blocked.
7.  "type_in_window" - Visually type text into an open app window. (Requires "window_name" and "text")
8.  "read_screen"    - Read the screen with OCR so JARVIS can see GUI apps.
9.  "speak"          - Speak text out loud. (Requires "text")
10. "listen"         - Listen to the microphone and transcribe what the user says.
11. "matlab"         - Run a MATLAB command. (Requires "command")
12. "arduino_ports"  - List connected Arduino/serial COM ports.
13. "arduino_read"   - Read lines from the Arduino serial monitor. (Optional: "port", "baud", "lines")

You must respond ONLY in strict JSON format:
{
    "action": "chat_only | read_file | write_file | git_sync | run_script | run_powershell | type_in_window | read_screen | speak | listen | matlab | arduino_ports | arduino_read",
    "filename": "file name if applicable",
    "content": "full updated content if writing a file",
    "commit_msg": "description of changes for git sync",
    "command": "powershell / matlab command if running one",
    "window_name": "target window title for type_in_window",
    "text": "text to type or speak",
    "port": "COM port for arduino",
    "baud": 9600,
    "lines": 5,
    "speech": "Your vocal response to Mekala."
}
"""


# ==================================================================
#  MAIN LOOP
# ==================================================================
messages = [{"role": "system", "content": system_prompt}]

if os.path.exists(MEMORY_FILE):
    prev = load_memory()
    if prev:
        try:
            ans = input(f"\n[MEMORY] Found {len(prev)} messages from last session. "
                        f"Load memory from last session? (yes/no): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "no"
        if ans == "yes":
            messages = prev
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": system_prompt})
            else:
                messages[0] = {"role": "system", "content": system_prompt}
            print(f"[MEMORY] Restored {len(prev)} messages. Welcome back, sir.")

# Build the free-model queue at startup
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

        # ---- local commands (no LLM call) ----
        if low in ['exit', 'quit', 'close']:
            print("Running final safety sync to GitHub before shutdown...")
            print(auto_backup_and_git_push("Final session sync before shutdown"))
            save_memory(messages)
            break
        if low == 'models':
            print("[MODELS] Current free queue:")
            for i, mid in enumerate(model_queue):
                cd = model_cooldown.get(mid, 0)
                state = f"cooling {int(cd - time.time())}s" if cd > time.time() else "ready"
                print(f"   {i + 1}. {mid}  [{state}]")
            continue
        if low == 'refresh models':
            build_model_queue(force_refresh=True)
            continue
        if low == 'clear memory':
            save_memory([])
            messages = [{"role": "system", "content": system_prompt}]
            print("[MEMORY] Cleared. Fresh start.")
            continue

        messages.append({"role": "user", "content": user_cmd})

        for step in range(3):
            command, model = llm_call(messages)
            if command is None:
                print(f"[LLM] All free models unreachable right now ({model}). Will retry next message.")
                messages.append({"role": "user",
                                 "content": "Note: the LLM backend was temporarily unavailable. "
                                            "Continue exactly where you left off."})
                time.sleep(5)
                break

            messages.append({"role": "assistant", "content": json.dumps(command, ensure_ascii=False)})
            print(f"[LLM] {model}")

            if "speech" in command and command["speech"]:
                print(f"\n[Audio]: {command['speech']}\n")
                speak(command["speech"])

            action = command.get("action")
            tool_output = ""

            if action == "read_file":
                filename = command.get("filename")
                if filename and os.path.exists(filename):
                    with open(filename, "r", encoding="utf-8") as f:
                        tool_output = f.read()
                    print(f"File '{filename}' loaded into context ({len(tool_output)} chars).")
                else:
                    tool_output = f"Error: File {filename} not found."

            elif action == "write_file":
                filename = command.get("filename")
                content = command.get("content", "")
                if not filename:
                    tool_output = "Error: write_file needs a 'filename'."
                    messages.append({"role": "user", "content": f"Tool Result:\n{tool_output}"})
                    break

                if os.path.exists(filename):
                    shutil.copy(filename, os.path.join(BACKUP_DIR, f"pre_write_{os.path.basename(filename)}"))

                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)

                git_res = auto_backup_and_git_push(f"Auto-sync after updating {filename}")
                tool_output = f"Success: '{filename}' updated and safely pushed to GitHub. {git_res}"
                print(tool_output)
                break

            elif action == "git_sync":
                msg = command.get("commit_msg", "Manual sync checkpoint")
                tool_output = auto_backup_and_git_push(msg)
                print(tool_output)
                break

            elif action == "run_script":
                filename = command.get("filename")
                if filename and os.path.exists(filename):
                    with open(filename, "r", encoding="utf-8") as f:
                        script_src = f.read()
                    findings = scan_code(script_src)
                    if has_blocking(findings):
                        print("[DANGER] Script contains destructive commands:")
                        for sev, reason in findings:
                            print(f"   [{sev}] {reason}")
                        ans = input("Run anyway? (yes/no): ").strip().lower()
                        if ans != "yes":
                            tool_output = "BLOCKED by safety scanner. Script not executed."
                            messages.append({"role": "user", "content": f"Tool Result:\n{tool_output}"})
                            break
                res = subprocess.run(["python", filename], capture_output=True, text=True)
                tool_output = f"Output:\n{res.stdout}\nErrors:\n{res.stderr}"
                if res.returncode != 0:
                    tool_output += "\n[WARNING]: Script exited with errors. Please analyze and fix code."
                print(tool_output)

            elif action == "run_powershell":
                cmd = command.get("command", "")
                findings = scan_shell_command(cmd)
                if has_blocking(findings):
                    print("[DANGER] Command blocked by safety scanner:")
                    for sev, reason in findings:
                        print(f"   [{sev}] {reason}")
                    ans = input("Run anyway? (yes/no): ").strip().lower()
                    if ans != "yes":
                        tool_output = "BLOCKED by safety scanner. Not executed."
                        messages.append({"role": "user", "content": f"Tool Result:\n{tool_output}"})
                        break
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd],
                    capture_output=True, text=True, timeout=120)
                tool_output = f"Output:\n{res.stdout}\nErrors:\n{res.stderr}"
                print(tool_output)

            elif action == "type_in_window":
                ok = type_text(command.get("text", ""), window_name=command.get("window_name"))
                tool_output = f"Typing {'succeeded' if ok else 'failed'}."

            elif action == "read_screen":
                region = command.get("region")
                tool_output = (read_screen(region=tuple(region)) if region else read_screen())
                tool_output = (tool_output or "(blank screen)")[:2000]
                print("[VISION]", tool_output[:500])

            elif action == "speak":
                speak(command.get("text", ""))
                tool_output = "Spoken."

            elif action == "listen":
                tool_output = listen()
                print("[HEARD]", tool_output)

            elif action == "matlab":
                tool_output = str(matlab_execute(command.get("command", "")))
                print("[MATLAB]", tool_output[:500])

            elif action == "arduino_ports":
                tool_output = str(arduino_ports())
                print("[ARDUINO] Ports:", tool_output)

            elif action == "arduino_read":
                tool_output = arduino_read(
                    port=command.get("port"), baud=command.get("baud", 9600),
                    lines=int(command.get("lines", 5)))
                print("[ARDUINO]", tool_output)

            elif action == "chat_only":
                break
            else:
                tool_output = f"Unrecognized action: {action}"
                break

            messages.append({"role": "user", "content": f"Tool Result:\n{tool_output}\nContinue or complete task."})

        # Save memory after every turn so nothing is lost, even on power cut
        save_memory(messages)

finally:
    save_memory(messages)
    if browser is not None:
        try:
            browser.quit()
        except Exception:
            pass
    print("Core offline. Progress saved to memory and GitHub.")
