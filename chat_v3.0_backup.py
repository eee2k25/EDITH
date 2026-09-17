"""
=====================================================================
  J.A.R.V.I.S. — Autonomous Core v3.1  (MERGED, SELF-CONTAINED)
=====================================================================
Kept from your v3.0:
  * OpenRouter (gpt-4o-mini) strict-JSON action loop
  * GitHub auto-sync + local timestamped backups
  * read_file / write_file / git_sync / run_script / run_powershell

NEW in v3.1 (all merged inline so a single file is hard to lose):
  * PERSISTENT MEMORY  -> memory/jarvis_memory.json (survives power cuts)
  * SAFETY GUARD       -> run_powershell blocked before destructive commands
  * type_in_window     -> visually type into ANY app (focus trick + paste)
  * read_screen        -> see GUI apps via pytesseract OCR
  * speak / listen     -> voice out (pyttsx3/SAPI) + voice in (mic)
  * matlab             -> drive MATLAB via COM automation server
  * arduino_ports / arduino_read -> serial monitor over USB

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
# Optional third-party imports — all guarded so one missing package
# can never crash the whole core.
# ------------------------------------------------------------------
try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # slam mouse to top-left corner to abort typing
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

# ------------------------------------------------------------------
# Console encoding safety (prevents UnicodeEncodeError crashes)
# ------------------------------------------------------------------
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

WORKSPACE_DIR = r"C:\WINDOWS\system32\JARVIS-making"
BACKUP_DIR = os.path.join(WORKSPACE_DIR, "backups")
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "jarvis_memory.json")
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

print("=" * 55)
print("   J.A.R.V.I.S. - AUTONOMOUS CORE v3.1 (MERGED)")
print("=" * 55)

# ------------------------------------------------------------------
# Browser module (your jarvis package) — guarded
# ------------------------------------------------------------------
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
    print("       Add  JARVIS_LLM_API_KEY=sk-...  to a .env file in JARVIS-making.")


# ==================================================================
#  SAFETY SCANNER (v2) — no more false "rm -rf"/"format" alarms
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
    """Scan one shell/PowerShell command line JARVIS is about to RUN."""
    return _scan_command_lines(command)


def scan_code(code):
    """Scan a block of code for destructive commands hidden in exec calls."""
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
#  VISUAL TYPING — types into any open window
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
    """Bring a window to the front, defeating Windows foreground-lock."""
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
    """Visually type `text` into the window matching `window_name`."""
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
#  VISION — screen reading (pytesseract OCR)
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
#  VOICE — output (pyttsx3 + Windows SAPI fallback) and input (mic)
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
#  MATLAB — COM automation server
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
#  ARDUINO — serial monitor
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
        time.sleep(2.0)  # let the Arduino auto-reset finish
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
#  PERSISTENT MEMORY — never lose progress again
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
#  GITHUB + LOCAL BACKUP (kept from your v3.0)
# ==================================================================
def auto_backup_and_git_push(commit_msg="Auto-save progress checkpoint"):
    """Local timestamped backup + GitHub push to prevent data loss."""
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
#  SYSTEM PROMPT — now with all the new actions
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


def _extract_json(raw):
    """Robustly pull a JSON object out of the model's reply (handles code fences)."""
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


# ==================================================================
#  MAIN LOOP
# ==================================================================
messages = [{"role": "system", "content": system_prompt}]

# Load last session's memory so progress is never lost
if os.path.exists(MEMORY_FILE):
    prev = load_memory()
    if prev:
        ans = input(f"\n[MEMORY] Found {len(prev)} messages from last session. "
                    f"Load memory from last session? (yes/no): ").strip().lower()
        if ans == "yes":
            messages = prev
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": system_prompt})
            else:
                messages[0] = {"role": "system", "content": system_prompt}
            print(f"[MEMORY] Restored {len(prev)} messages. Welcome back, sir.")


def _api_payload(messages):
    """Send the full conversation but cap context sent to the API to control cost."""
    if len(messages) <= 100:
        return messages
    return [messages[0]] + messages[-99:]


try:
    while True:
        try:
            user_cmd = input("\nJ.A.R.V.I.S.> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nShutting down...")
            break

        if not user_cmd:
            continue

        if user_cmd.lower() in ['exit', 'quit', 'close']:
            print("Running final safety sync to GitHub before shutdown...")
            print(auto_backup_and_git_push("Final session sync before shutdown"))
            save_memory(messages)
            break

        messages.append({"role": "user", "content": user_cmd})

        for step in range(3):
            try:
                headers = {
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": _api_payload(messages),
                    "response_format": {"type": "json_object"},
                }
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers, json=payload, timeout=120)

                if response.status_code != 200:
                    raise RuntimeError(f"API {response.status_code}: {response.text[:300]}")

                raw_content = response.json()['choices'][0]['message']['content']
                command = _extract_json(raw_content)
                if command is None:
                    raise RuntimeError(f"Model did not return valid JSON: {raw_content[:300]}")

                messages.append({"role": "assistant", "content": raw_content})

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

                    # Auto backup before overwriting
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
                    region = command.get("region")  # optional [x, y, w, h]
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

            except Exception as e:
                error_msg = f"Execution Error: {str(e)}"
                print(error_msg)
                messages.append({"role": "user", "content": f"Error encountered: {error_msg}. Fix the issue."})
                break

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
