import os
import json
import subprocess
import requests
import shutil
import datetime
import signal
import sys
import time
import threading
import pyperclip
import pyautogui
import psutil
import win32gui
import win32con
import win32process
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from dotenv import load_dotenv
from jarvis.config import Settings
from jarvis.modules.browser import BrowserModule

load_dotenv()
API_KEY = os.getenv("JARVIS_LLM_API_KEY")

JARVIS_DIR = r"C:\WINDOWS\system32\JARVIS-making"
BACKUP_DIR = os.path.join(JARVIS_DIR, "backups")
MEMORY_FILE = os.path.join(JARVIS_DIR, "memory", "jarvis_memory.json")
LOG_FILE = os.path.join(JARVIS_DIR, "logs", "jarvis_log.json")
STATS_FILE = os.path.join(JARVIS_DIR, "logs", "performance_stats.json")
ERROR_LOG = os.path.join(JARVIS_DIR, "logs", "error_history.json")

for folder in ["backups", "memory", "logs", "versions"]:
    os.makedirs(os.path.join(JARVIS_DIR, folder), exist_ok=True)

AI_SITES = {
    "claude.ai": {"name": "Claude", "code_selector": "pre code", "input_selector": "div[contenteditable='true']"},
    "gemini.google.com": {"name": "Gemini", "code_selector": "code-block pre", "input_selector": "rich-textarea div[contenteditable]"},
    "chatgpt.com": {"name": "ChatGPT", "code_selector": "pre code", "input_selector": "div[contenteditable='true']"},
    "arena.ai": {"name": "Arena AI", "code_selector": "pre code", "input_selector": "textarea"},
    "chat.openai.com": {"name": "OpenAI", "code_selector": "pre code", "input_selector": "textarea"}
}

TARGET_APPS = {
    "arduino": {"name": "Arduino IDE", "select_all_first": True, "confirm_before": False},
    "matlab": {"name": "MATLAB", "select_all_first": True, "confirm_before": True},
    "simulink": {"name": "Simulink", "select_all_first": False, "confirm_before": True},
    "winword": {"name": "Microsoft Word", "select_all_first": False, "confirm_before": True},
    "powerpnt": {"name": "PowerPoint", "select_all_first": False, "confirm_before": True},
    "code": {"name": "VS Code", "select_all_first": True, "confirm_before": False},
    "notepad": {"name": "Notepad", "select_all_first": True, "confirm_before": False}
}

DANGEROUS_PATTERNS = [
    "rm -rf", "del /f", "format", "shutdown",
    "os.remove", "shutil.rmtree", "DROP TABLE",
    "DELETE FROM", "eval(", "exec("
]

# ============================================================
# CORE FUNCTIONS
# ============================================================

def backup_self():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    src = os.path.join(JARVIS_DIR, "chat.py")
    dst = os.path.join(BACKUP_DIR, f"chat_backup_{timestamp}.py")
    shutil.copy(src, dst)
    print(f"[BACKUP] Saved: {dst}")
    return dst

def save_memory(messages):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2)
    except Exception as e:
        print(f"[MEMORY] Save error: {e}")

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[MEMORY] Found {len(data)} messages from last session.")
            return data
    except Exception as e:
        print(f"[MEMORY] Load error: {e}")
    return []

def log_action(action, result, success):
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "action": action,
            "result": str(result)[:200],
            "success": success
        })
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
    except:
        pass

def log_error(error_text, context=""):
    try:
        errors = []
        if os.path.exists(ERROR_LOG):
            with open(ERROR_LOG, "r", encoding="utf-8") as f:
                errors = json.load(f)
        errors.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "error": error_text[:500],
            "context": context,
            "resolved": False
        })
        with open(ERROR_LOG, "w", encoding="utf-8") as f:
            json.dump(errors, f, indent=2)
    except:
        pass

def update_stats(action, success):
    try:
        stats = {}
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
        if action not in stats:
            stats[action] = {"success": 0, "fail": 0, "total": 0}
        stats[action]["total"] += 1
        if success:
            stats[action]["success"] += 1
        else:
            stats[action]["fail"] += 1
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except:
        pass

def show_stats():
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
            print("\n[JARVIS PERFORMANCE STATS]")
            print("-" * 45)
            for action, data in stats.items():
                rate = (data["success"] / data["total"] * 100) if data["total"] > 0 else 0
                print(f"  {action:<20} | {data['total']:>3} runs | {rate:.1f}% success")
            print("-" * 45)
        else:
            print("[STATS] No stats recorded yet.")
    except Exception as e:
        print(f"[STATS] Error: {e}")

def safe_write_file(filename, content):
    is_self = "chat.py" in filename
    if is_self:
        print("\n[WARNING] JARVIS wants to modify its own source code.")
        confirm = input("Approve self-modification? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("[BLOCKED] Cancelled.")
            return "Self-modification blocked."
        backup_self()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    log_action("write_file", f"Wrote {filename}", True)
    update_stats("write_file", True)
    return f"Success: {filename} updated."

# ============================================================
# POWERSHELL EXECUTOR - JARVIS runs its own commands
# ============================================================

def run_powershell(command, timeout=120):
    """JARVIS executes PowerShell commands and reads output directly"""
    print(f"[PS] Running: {command[:80]}...")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        output = result.stdout.strip()
        errors = result.stderr.strip()
        combined = ""
        if output:
            combined += output
        if errors:
            combined += "\nERROR: " + errors
        print(f"[PS] Output: {combined[:300]}")
        log_action("run_powershell", combined[:200], result.returncode == 0)
        update_stats("run_powershell", result.returncode == 0)
        return combined if combined else "Command completed with no output"
    except subprocess.TimeoutExpired:
        return "PowerShell command timed out"
    except Exception as e:
        return f"PowerShell error: {e}"

def auto_fix_error(error_text, messages):
    """JARVIS sees an error and automatically tries to fix it"""
    print(f"\n[AUTO-FIX] Error detected. JARVIS is analyzing...")
    log_error(error_text, "auto_fix_triggered")

    fix_prompt = f"""
You are JARVIS. You just encountered this error:

{error_text}

Analyze this error and provide the fix using run_powershell action.
Run the necessary PowerShell commands to fix this automatically.
Do not ask the user - just fix it.

Respond in JSON:
{{
    "action": "run_powershell",
    "command": "the powershell command to fix this",
    "speech": "What you are doing to fix this"
}}
"""
    messages.append({"role": "user", "content": fix_prompt})
    return messages

# ============================================================
# UNIVERSAL AGENT
# ============================================================

edge_driver = None
agent_running = False
last_codes_seen = []

def connect_edge():
    global edge_driver
    try:
        options = Options()
        options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        edge_driver = webdriver.Edge(options=options)
        print("[AGENT] Connected to Edge browser")
        return True
    except Exception as e:
        edge_driver = None
        return False

def is_edge_alive():
    global edge_driver
    try:
        if edge_driver is None:
            return False
        _ = edge_driver.current_url
        return True
    except:
        edge_driver = None
        return False

def safe_navigate(url):
    global edge_driver
    if not is_edge_alive():
        print("[AGENT] Edge disconnected. Reconnecting...")
        if not connect_edge():
            return False
    try:
        edge_driver.get(url)
        print(f"[BROWSER] Navigated to {url}")
        return True
    except Exception as e:
        print(f"[BROWSER] Navigation error: {e}")
        return False

def is_dangerous(code):
    code_lower = code.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in code_lower:
            return True, pattern
    return False, None

def get_open_windows():
    windows = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc = psutil.Process(pid)
                    windows.append({
                        "hwnd": hwnd,
                        "title": title,
                        "process": proc.name().lower(),
                        "pid": pid
                    })
                except:
                    pass
    win32gui.EnumWindows(callback, None)
    return windows

def find_target_app(windows):
    for window in windows:
        proc_name = window["process"].replace(".exe", "")
        for app_key, app_info in TARGET_APPS.items():
            if app_key in proc_name:
                return window, app_info
    return None, None

def bring_window_to_front(hwnd):
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        return True
    except:
        return False

def paste_code_into_app(window, app_info, code):
    app_name = app_info["name"]
    dangerous, pattern = is_dangerous(code)
    if dangerous:
        print(f"\n[DANGER] Code contains: {pattern}")
        confirm = input(f"Paste into {app_name} anyway? (yes/no): ").strip().lower()
        if confirm != "yes":
            return False
    elif app_info["confirm_before"]:
        confirm = input(f"\n[AGENT] Paste code into {app_name}? (yes/no): ").strip().lower()
        if confirm != "yes":
            return False
    pyperclip.copy(code)
    if bring_window_to_front(window["hwnd"]):
        time.sleep(0.3)
        if app_info["select_all_first"]:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        print(f"[OK] Pasted into {app_name}")
        log_action("paste_to_app", app_name, True)
        update_stats("paste_to_app", True)
        return True
    return False

def extract_codes_from_tab(driver, url):
    extracted = []
    for site_key, site_info in AI_SITES.items():
        if site_key in url:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, site_info["code_selector"])
                for el in elements:
                    code = el.text.strip()
                    if code and len(code) > 20:
                        extracted.append({
                            "site": site_info["name"],
                            "code": code,
                            "length": len(code)
                        })
            except:
                pass
            break
    return extracted

def universal_watcher_thread():
    global agent_running, edge_driver, last_codes_seen
    print("[AGENT] Background watcher running...")
    while agent_running:
        try:
            if not is_edge_alive():
                time.sleep(5)
                connect_edge()
                continue
            current_url = edge_driver.current_url
            current_codes = extract_codes_from_tab(edge_driver, current_url)
            if current_codes:
                new_codes = [
                    c for c in current_codes
                    if c["code"] not in [lc["code"] for lc in last_codes_seen]
                ]
                if new_codes:
                    print(f"\n[AGENT] NEW CODE DETECTED - {len(new_codes)} block(s)")
                    for i, code_block in enumerate(new_codes):
                        print(f"\n--- Block {i+1} ({code_block['length']} chars) ---")
                        print(code_block["code"][:200])
                        print("---")
                        open_windows = get_open_windows()
                        target_window, target_app = find_target_app(open_windows)
                        if target_window and target_app:
                            print(f"[AGENT] Target: {target_app['name']}")
                            paste_code_into_app(target_window, target_app, code_block["code"])
                        else:
                            pyperclip.copy(code_block["code"])
                            print("[AGENT] No target app open. Code copied to clipboard.")
                    last_codes_seen = current_codes
            time.sleep(3)
        except Exception as e:
            time.sleep(5)

# ============================================================
# CRASH PROTECTION
# ============================================================

messages = []

def handle_exit(sig, frame):
    global agent_running
    print("\n[JARVIS] Saving and shutting down...")
    agent_running = False
    save_memory(messages)
    print("[JARVIS] Goodbye, sir.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)

# ============================================================
# BOOT
# ============================================================

print("=" * 55)
print("  J.A.R.V.I.S. - UNIFIED SYSTEM BOOTING")
print("=" * 55)

settings = Settings()
browser = BrowserModule(settings)
browser.start()

print("[SELF-IMPROVEMENT] Online")
print("[CRASH PROTECTION] Online")
print("[AUTO-FIX ENGINE] Online")
print("[PERSISTENT MEMORY] Loading...")
print("[AGENT] Connecting to Edge...")

if connect_edge():
    agent_running = True
    watcher = threading.Thread(target=universal_watcher_thread, daemon=True)
    watcher.start()
    print("[AGENT] Universal watcher ONLINE")
else:
    print("[AGENT] Edge not found. Type: agent reconnect")

system_prompt = """
You are J.A.R.V.I.S., an advanced autonomous engineering assistant.
Your operator is Mekala Ganesh, an EEE student developing IoT systems.

You have a CRITICAL new capability: run_powershell
Use this to fix errors, install packages, run system commands ALL BY YOURSELF.
Never ask the user to run commands manually. Do it yourself with run_powershell.

When you see an error:
1. Analyze it
2. Use run_powershell to fix it automatically
3. Verify the fix worked
4. Report back to Mekala

Available actions:
1. "chat_only" - Conversation
2. "open_url" - Navigate browser (Requires "url")
3. "click_element" - Click element (Requires "selector")
4. "read_file" - Read local file (Requires "filename")
5. "write_file" - Write local file (Requires "filename" and "content")
6. "run_script" - Run python script (Requires "filename")
7. "run_powershell" - Run PowerShell command directly (Requires "command")
8. "show_stats" - Show performance stats

IMPORTANT RULES:
- When user pastes an error, use run_powershell to fix it yourself
- Never tell user to run commands manually
- Chain multiple run_powershell calls to fully solve problems
- Always verify fixes worked by running a check command after fixing

Respond ONLY in strict JSON:
{
    "action": "action_name",
    "url": "https://...",
    "selector": "CSS selector",
    "filename": "filename",
    "content": "full content",
    "command": "PowerShell command to run",
    "speech": "Your response to Mekala"
}
"""

old_memory = load_memory()
if old_memory:
    use_memory = input("Load memory from last session? (yes/no): ").strip().lower()
    messages = old_memory if use_memory == "yes" else [{"role": "system", "content": system_prompt}]
    if use_memory == "yes":
        print(f"[MEMORY] Restored {len(messages)} messages.")
else:
    messages = [{"role": "system", "content": system_prompt}]

print("\n[JARVIS] All systems online.")
print("Commands: 'stats' | 'memory' | 'clear memory' | 'agent status' | 'agent reconnect' | 'exit'")
print("[JARVIS] Paste ANY error directly into me and I will fix it myself\n")

# ============================================================
# MAIN LOOP
# ============================================================

while True:
    try:
        user_cmd = input("J.A.R.V.I.S.> ").strip()
    except KeyboardInterrupt:
        handle_exit(None, None)

    if user_cmd.lower() in ['exit', 'quit', 'close']:
        agent_running = False
        save_memory(messages)
        print("Shutting down. Goodbye, sir.")
        browser.quit()
        break

    if user_cmd.lower() == 'stats':
        show_stats()
        continue

    if user_cmd.lower() == 'memory':
        user_msgs = [m for m in messages if m["role"] == "user"]
        print(f"[MEMORY] {len(messages)} total | {len(user_msgs)} from you")
        continue

    if user_cmd.lower() == 'clear memory':
        messages = [{"role": "system", "content": system_prompt}]
        print("[MEMORY] Cleared.")
        continue

    if user_cmd.lower() == 'agent status':
        alive = is_edge_alive()
        print(f"[AGENT] Edge: {'ALIVE' if alive else 'DEAD'}")
        print(f"[AGENT] Watcher: {agent_running}")
        print(f"[AGENT] Codes seen: {len(last_codes_seen)}")
        continue

    if user_cmd.lower() == 'agent reconnect':
        print("[AGENT] Reconnecting...")
        if connect_edge():
            if not agent_running:
                agent_running = True
                watcher = threading.Thread(target=universal_watcher_thread, daemon=True)
                watcher.start()
            print("[AGENT] Reconnected")
        else:
            print("[AGENT] Failed. Make sure Edge debug port is open.")
        continue

    if not user_cmd:
        continue

    messages.append({"role": "user", "content": user_cmd})

    for step in range(5):
        print(f"[Step {step+1}] Thinking...")

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "response_format": {"type": "json_object"}
        }

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload
            )

            raw_content = response.json()['choices'][0]['message']['content']
            command = json.loads(raw_content)
            messages.append({"role": "assistant", "content": raw_content})

            if "speech" in command:
                print(f"\n[JARVIS]: {command['speech']}\n")

            action = command.get("action")
            tool_output = ""

            if action == "open_url":
                url = command.get("url")
                if safe_navigate(url):
                    tool_output = f"Navigated to {url}"
                    log_action(action, url, True)
                    update_stats(action, True)
                else:
                    tool_output = f"Failed to navigate to {url}"
                    log_action(action, url, False)
                    update_stats(action, False)

            elif action == "click_element":
                browser.click(command.get("selector"))
                tool_output = "Element clicked."
                log_action(action, tool_output, True)
                update_stats(action, True)

            elif action == "read_file":
                filename = command.get("filename")
                print(f"[Executing] Reading '{filename}'...")
                if os.path.exists(filename):
                    with open(filename, "r", encoding="utf-8") as f:
                        file_text = f.read()
                    line_count = len(file_text.splitlines())
                    tool_output = "Content of " + filename + " (" + str(line_count) + " lines):\n" + file_text
                    print(f"[OK] {line_count} lines loaded.")
                    log_action(action, filename, True)
                    update_stats(action, True)
                else:
                    tool_output = "Error: File not found: " + filename
                    log_action(action, tool_output, False)
                    update_stats(action, False)

            elif action == "write_file":
                filename = command.get("filename")
                content = command.get("content")
                print(f"[Executing] Writing '{filename}'...")
                tool_output = safe_write_file(filename, content)
                print(tool_output)
                break

            elif action == "run_script":
                filename = command.get("filename")
                print(f"[Executing] Running '{filename}'...")
                res = subprocess.run(
                    ["python", filename],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                tool_output = "Output:\n" + res.stdout + "\n" + res.stderr
                print(tool_output)
                log_action(action, tool_output[:200], True)
                update_stats(action, True)

            elif action == "run_powershell":
                ps_command = command.get("command")
                print(f"[Executing] PowerShell: {ps_command[:80]}...")
                tool_output = run_powershell(ps_command)
                print(f"[PS Result]: {tool_output[:300]}")
                log_action(action, tool_output[:200], True)
                update_stats(action, True)

            elif action == "show_stats":
                show_stats()
                break

            elif action == "chat_only":
                log_action(action, "Chat delivered", True)
                update_stats(action, True)
                break

            else:
                print(f"[JARVIS] Unknown action: {action}")
                break

            messages.append({
                "role": "user",
                "content": "Tool Result:\n" + tool_output + "\nProceed or complete the task."
            })

        except KeyboardInterrupt:
            handle_exit(None, None)
        except Exception as e:
            print(f"[ERROR] {e}")
            log_action("error", str(e), False)
            update_stats("error", False)
            break

    save_memory(messages)
