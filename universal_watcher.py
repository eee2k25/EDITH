import ctypes
import psutil
import subprocess
import time

# Function to get all open windows
def get_open_windows():
    open_windows = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            hwnd = ctypes.windll.user32.FindWindow(None, proc.info['name'])
            if hwnd:
                open_windows.append((proc.info['name'], proc.info['pid']))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return open_windows

# Function to ask user which window to paste into
def ask_user_for_window(windows):
    print("Select a window to paste into:")
    for i, (name, pid) in enumerate(windows):
        print(f"{i + 1}: {name} (PID: {pid})")
    choice = int(input("Enter the number of the window: ")) - 1
    return windows[choice][1]  # Return the PID of the chosen window

# Main loop checking for new code (pseudo-code)
while True:
    new_code_detected = check_for_new_code()  # Implement your code detection logic
    if new_code_detected:
        windows = get_open_windows()
        pid_to_paste = ask_user_for_window(windows)
        # Implement pasting logic into the selected window (using hwnd or other means)
    time.sleep(5)  # Check every 5 seconds