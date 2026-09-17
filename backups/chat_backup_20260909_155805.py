import os
import json
import subprocess
import requests
import shutil
import datetime
from dotenv import load_dotenv
from jarvis.config import Settings
from jarvis.modules.browser import BrowserModule

load_dotenv()
API_KEY = os.getenv("JARVIS_LLM_API_KEY")

# ============================================================
# SELF-IMPROVEMENT CORE SYSTEMS
# ============================================================

JARVIS_DIR = "C:\\WINDOWS\\system32\\JARVIS-making"
BACKUP_DIR = os.path.join(JARVIS_DIR, "backups")
MEMORY_FILE = os.path.join(JARVIS_DIR, "memory", "jarvis_memory.json")
LOG_FILE = os.path.join(JARVIS_DIR, "logs", "jarvis_log.json")
STATS_FILE = os.path.join(JARVIS_DIR, "logs", "performance_stats.json")

# Create folders if they don't exist
for folder in ["backups", "memory", "logs", "versions"]:
    os.makedirs(os.path.join(JARVIS_DIR, folder), exist_ok=True)


def backup_self():
    """Backup chat.py before any self-modification"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    src = os.path.join(JARVIS_DIR, "chat.py")
    dst = os.path.join(BACKUP_DIR, f"chat_backup_{timestamp}.py")
    shutil.copy(src, dst)
    print(f"[BACKUP] Saved: {dst}")
    return dst


def save_memory(messages):
    """Save conversation history between sessions"""
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2)
    except Exception as e:
        print(f"[MEMORY] Save error: {e}")


def load_memory():
    """Load conversation history from last session"""
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"[MEMORY] Loaded {len(data)} messages from last session.")
                return data
    except Exception as e:
        print(f"[MEMORY] Load error: {e}")
    return []


def log_action(action, result, success):
    """Log every action JARVIS takes for performance tracking"""
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
    except Exception as e:
        print(f"[LOG] Error: {e}")


def update_stats(action, success):
    """Track success and failure rates per action type"""
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
    except Exception as e:
        print(f"[STATS] Error: {e}")


def show_stats():
    """Display JARVIS performance stats"""
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
            print("\n[JARVIS PERFORMANCE STATS]")
            print("-" * 40)
            for action, data in stats.items():
                rate = (data["success"] / data["total"] * 100) if data["total"] > 0 else 0
                print(f"{action}: {data['total']} runs | {rate:.1f}% success rate")
            print("-" * 40)
        else:
            print("[STATS] No stats recorded yet.")
    except Exception as e:
        print(f"[STATS] Error: {e}")


def safe_write_file(filename, content):
    """Safe file write with backup and user approval for self-modification"""
    is_self = "chat.py" in filename
    if is_self:
        print("\n[WARNING] JARVIS wants to modify its own source code.")
        print(f"File: {filename}")
        confirm = input("Approve self-modification? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("[BLOCKED] Self-modification cancelled by operator.")
            return "Self-modification blocked by operator."
        backup_self()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    log_action("write_file", f"Wrote {filename}", True)
    update_stats("write_file", True)
    return f"Success: {filename} updated."


# ============================================================
# MAIN JARVIS BOOT
# ============================================================

print("Initializing J.A.R.V.I.S. Recursive Agent Core...")
settings = Settings()
browser = BrowserModule(settings)
browser.start()

print("\n[SELF-IMPROVEMENT ENGINE] Online")
print("[PERSISTENT MEMORY] Loading...")

system_prompt = """
You are J.A.R.V.I.S., an advanced autonomous engineering assistant capable of self-modification.
Your operator is Mekala Ganesh, an EEE student developing IoT systems.

You can execute multi-step tool loops. When a user asks you to inspect and fix or clean a file:
1. First, use action "read_file" to check the file.
2. Once you receive the file content back in the tool result, analyze it, fix the problem, and immediately output action "write_file" with the filename and full updated content.

Available actions:
1. "chat_only" - For conversation.
2. "open_url" - Opens a web link. (Requires "url")
3. "click_element" - Clicks a CSS selector. (Requires "selector")
4. "read_file" - Reads code from a local file to inspect it. (Requires "filename")
5. "write_file" - Saves or updates code in a file. (Requires "filename" and "content")
6. "run_script" - Executes a python script. (Requires "filename")
7. "show_stats" - Shows JARVIS performance statistics.

You must respond ONLY in strict JSON format:
{
    "action": "chat_only | open_url | click_element | read_file | write_file | run_script | show_stats",
    "url": "https://...",
    "selector": "CSS selector",
    "filename": "file name",
    "content": "Full updated code content if rewriting a file",
    "speech": "Your vocal response to Mekala."
}
"""

# Load persistent memory from last session
old_memory = load_memory()
if old_memory:
    use_memory = input("Load memory from last session? (yes/no): ").strip().lower()
    if use_memory == "yes":
        messages = old_memory
        print(f"[MEMORY] Restored {len(messages)} messages from last session.")
    else:
        messages = [{"role": "system", "content": system_prompt}]
else:
    messages = [{"role": "system", "content": system_prompt}]

print("\nRecursive Self-Modifying System Online.")
print("Type 'stats' to see performance. Type 'exit' to shut down.\n")

try:
    while True:
        user_cmd = input("J.A.R.V.I.S.> ").strip()

        if user_cmd.lower() in ['exit', 'quit', 'close']:
            break

        if user_cmd.lower() == 'stats':
            show_stats()
            continue

        if user_cmd.lower() == 'clear memory':
            messages = [{"role": "system", "content": system_prompt}]
            print("[MEMORY] Cleared. Fresh session started.")
            continue

        if not user_cmd:
            continue

        messages.append({"role": "user", "content": user_cmd})

        for step in range(5):
            print(f"[Step {step+1}] Thinking and planning workflow...")

            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": messages,
                "response_format": {"type": "json_object"}
            }

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload
            )

            try:
                raw_content = response.json()['choices'][0]['message']['content']
                command = json.loads(raw_content)
                messages.append({"role": "assistant", "content": raw_content})

                if "speech" in command:
                    print(f"\n[JARVIS]: {command['speech']}\n")

                action = command.get("action")
                tool_output = ""
                success = True

                if action == "open_url":
                    browser.open(command.get("url"))
                    tool_output = "Browser successfully navigated to URL."
                    log_action(action, tool_output, True)
                    update_stats(action, True)

                elif action == "click_element":
                    browser.click(command.get("selector"))
                    tool_output = "Element successfully clicked."
                    log_action(action, tool_output, True)
                    update_stats(action, True)

                elif action == "read_file":
                    filename = command.get("filename")
                    print(f"[Executing] Reading '{filename}'...")
                    if os.path.exists(filename):
                        with open(filename, "r", encoding="utf-8") as f:
                            file_text = f.read()
                        tool_output = "Content of " + filename + ":\n" + file_text
                        print(f"[OK] File read ({len(file_text)} characters loaded).")
                        log_action(action, f"Read {filename}", True)
                        update_stats(action, True)
                    else:
                        tool_output = "Error: File " + filename + " not found."
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
                        text=True
                    )
                    tool_output = "Script output:\n" + res.stdout + "\n" + res.stderr
                    print(tool_output)
                    log_action(action, tool_output[:200], True)
                    update_stats(action, True)

                elif action == "show_stats":
                    show_stats()
                    break

                elif action == "chat_only":
                    log_action(action, "Chat response", True)
                    update_stats(action, True)
                    break

                else:
                    tool_output = "Unrecognized action."
                    print(f"[JARVIS]: {tool_output}")
                    break

                messages.append({
                    "role": "user",
                    "content": "Tool Execution Result:\n" + tool_output + "\nNow proceed to the next step or complete the request."
                })

            except Exception as e:
                print(f"[ERROR] Execution Error: {e}")
                log_action("unknown", str(e), False)
                update_stats("error", False)
                break

        # Save memory after every interaction
        save_memory(messages)

finally:
    print("\nSaving memory before shutdown...")
    save_memory(messages)
    print("Shutting down core systems. Goodbye, sir.")
    browser.quit()
