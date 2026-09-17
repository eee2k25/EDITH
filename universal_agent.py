import time
import json
import os
import subprocess
import threading
import pyperclip
import pyautogui
import win32gui
import win32con
import win32process
import psutil
from PIL import ImageGrab
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from datetime import datetime

# ============================================================
# JARVIS UNIVERSAL AGENT
# Watches all AI tabs and all apps
# ============================================================

LOG_DIR = "C:\\WINDOWS\\system32\\JARVIS-making\\logs"
MEMORY_DIR = "C:\\WINDOWS\\system32\\JARVIS-making\\memory"
AGENT_LOG = os.path.join(LOG_DIR, "universal_agent_log.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

# ============================================================
# KNOWN AI SITES - Add more any time
# ============================================================

AI_SITES = {
    "claude.ai": {
        "name": "Claude",
        "code_selector": "pre code",
        "input_selector": "div[contenteditable='true']"
    },
    "gemini.google.com": {
        "name": "Gemini",
        "code_selector": "code-block pre",
        "input_selector": "rich-textarea div[contenteditable]"
    },
    "chatgpt.com": {
        "name": "ChatGPT",
        "code_selector": "pre code",
        "input_selector": "div[contenteditable='true']"
    },
    "arena.ai": {
        "name": "Arena AI",
        "code_selector": "pre code",
        "input_selector": "textarea"
    },
    "chat.openai.com": {
        "name": "OpenAI",
        "code_selector": "pre code",
        "input_selector": "textarea"
    }
}

# ============================================================
# KNOWN TARGET APPS - Where to paste code
# ============================================================

TARGET_APPS = {
    "arduino": {
        "name": "Arduino IDE",
        "paste_method": "keyboard",
        "select_all_first": True,
        "confirm_before": False
    },
    "matlab": {
        "name": "MATLAB",
        "paste_method": "keyboard",
        "select_all_first": True,
        "confirm_before": True
    },
    "simulink": {
        "name": "Simulink",
        "paste_method": "keyboard",
        "select_all_first": False,
        "confirm_before": True
    },
    "winword": {
        "name": "Microsoft Word",
        "paste_method": "keyboard",
        "select_all_first": False,
        "confirm_before": True
    },
    "powerpnt": {
        "name": "PowerPoint",
        "paste_method": "keyboard",
        "select_all_first": False,
        "confirm_before": True
    },
    "code": {
        "name": "VS Code",
        "paste_method": "keyboard",
        "select_all_first": True,
        "confirm_before": False
    },
    "notepad": {
        "name": "Notepad",
        "paste_method": "keyboard",
        "select_all_first": True,
        "confirm_before": False
    }
}

# ============================================================
# DANGEROUS COMMANDS - Always ask before running these
# ============================================================

DANGEROUS_PATTERNS = [
    "rm -rf",
    "del /f",
    "format",
    "shutdown",
    "os.remove",
    "shutil.rmtree",
    "DROP TABLE",
    "DELETE FROM",
    "subprocess.call",
    "eval(",
    "exec("
]


def log_event(event_type, details):
    try:
        logs = []
        if os.path.exists(AGENT_LOG):
            with open(AGENT_LOG, "r") as f:
                logs = json.load(f)
        logs.append({
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            "details": str(details)[:300]
        })
        with open(AGENT_LOG, "w") as f:
            json.dump(logs, f, indent=2)
    except:
        pass


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
    except Exception as e:
        print(f"[ERROR] Could not bring window to front: {e}")
        return False


def paste_code_into_app(window, app_info, code):
    app_name = app_info["name"]
    dangerous, pattern = is_dangerous(code)

    if dangerous:
        print(f"\n[DANGER DETECTED] Code contains: {pattern}")
        confirm = input(f"This code may be dangerous. Paste into {app_name}? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("[BLOCKED] Paste cancelled.")
            log_event("BLOCKED_DANGEROUS", f"Pattern: {pattern}")
            return False
    elif app_info["confirm_before"]:
        print(f"\n[JARVIS] Want to paste code into {app_name}?")
        confirm = input("Confirm? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("[SKIPPED] Paste skipped.")
            return False

    print(f"[JARVIS] Pasting into {app_name}...")
    pyperclip.copy(code)

    if bring_window_to_front(window["hwnd"]):
        time.sleep(0.3)
        if app_info["select_all_first"]:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        print(f"[OK] Code pasted into {app_name}")
        log_event("PASTE_SUCCESS", f"Pasted into {app_name}")
        return True

    return False


def send_output_to_ai(driver, ai_site, output_text):
    try:
        site_info = AI_SITES.get(ai_site, {})
        input_selector = site_info.get("input_selector", "textarea")
        elements = driver.find_elements(By.CSS_SELECTOR, input_selector)
        if elements:
            input_box = elements[-1]
            input_box.click()
            time.sleep(0.3)
            message = f"Here is the output from running your code:\n\n{output_text}\n\nPlease analyze this and suggest the next improvement."
            pyperclip.copy(message)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.3)
            print(f"[JARVIS] Output sent back to AI. Press Enter in the AI chat to submit.")
            log_event("OUTPUT_SENT", f"Sent to {ai_site}")
    except Exception as e:
        print(f"[ERROR] Could not send output to AI: {e}")


def extract_codes_from_tab(driver, url):
    extracted = []
    for site_key, site_info in AI_SITES.items():
        if site_key in url:
            try:
                selector = site_info["code_selector"]
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    code = el.text.strip()
                    if code and len(code) > 20:
                        extracted.append({
                            "site": site_info["name"],
                            "code": code,
                            "length": len(code)
                        })
                if extracted:
                    print(f"[JARVIS] Found {len(extracted)} code blocks on {site_info['name']}")
            except Exception as e:
                print(f"[ERROR] Extracting from {site_key}: {e}")
            break
    return extracted


# ============================================================
# MAIN WATCHER LOOP
# ============================================================

def start_universal_agent():
    print("=" * 55)
    print("  JARVIS UNIVERSAL AGENT - STARTING")
    print("=" * 55)
    print("[INFO] Connecting to your Edge browser...")
    print("[INFO] Make sure Edge was started with remote debugging")
    print()

    try:
        options = Options()
        options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        driver = webdriver.Edge(options=options)
        print("[OK] Connected to Edge browser")
    except Exception as e:
        print(f"[ERROR] Could not connect to Edge: {e}")
        print("[FIX] Run this command first:")
        print('  Start-Process "msedge" --args "--remote-debugging-port=9222"')
        return

    print("[JARVIS] Universal Agent is now watching...")
    print("[JARVIS] Open any AI site in Edge and I will detect code automatically")
    print("[JARVIS] Press Ctrl+C to stop\n")

    last_codes = []

    while True:
        try:
            current_url = driver.current_url
            current_codes = extract_codes_from_tab(driver, current_url)

            if current_codes:
                new_codes = [c for c in current_codes if c["code"] not in [lc["code"] for lc in last_codes]]

                if new_codes:
                    print(f"\n[NEW CODE DETECTED] {len(new_codes)} new block(s) found")

                    for i, code_block in enumerate(new_codes):
                        print(f"\n--- Code Block {i+1} ({code_block['length']} chars) ---")
                        print(code_block["code"][:200] + "..." if len(code_block["code"]) > 200 else code_block["code"])
                        print("---")

                        open_windows = get_open_windows()
                        target_window, target_app = find_target_app(open_windows)

                        if target_window and target_app:
                            print(f"[JARVIS] Target app detected: {target_app['name']}")
                            paste_code_into_app(target_window, target_app, code_block["code"])
                        else:
                            print("[JARVIS] No target app detected.")
                            print("[JARVIS] Open Arduino IDE, MATLAB, VS Code etc and I will paste automatically")
                            pyperclip.copy(code_block["code"])
                            print("[JARVIS] Code copied to clipboard as fallback")

                    last_codes = current_codes
                    log_event("NEW_CODE_DETECTED", f"{len(new_codes)} blocks from {current_url}")

            time.sleep(3)

        except KeyboardInterrupt:
            print("\n[JARVIS] Universal Agent shutting down...")
            break
        except Exception as e:
            time.sleep(5)

    print("[JARVIS] Universal Agent offline.")


if __name__ == "__main__":
    start_universal_agent()
