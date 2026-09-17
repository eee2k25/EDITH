import pyautogui
import sys
import time
import win32gui


def type_to_window(window_name, text):
    # Function to find the window handle by name
    def find_window(title):
        def callback(hwnd, titles):
            if title.lower() in win32gui.GetWindowText(hwnd).lower():
                titles.append(hwnd)
        titles = []
        win32gui.EnumWindows(callback, titles)
        return titles[0] if titles else None

    # Find the window by name
    hwnd = find_window(window_name)
    if hwnd:
        win32gui.ShowWindow(hwnd, 5)  # Set the window to be active
        win32gui.SetForegroundWindow(hwnd)  # Bring the window to front
        time.sleep(1)  # Wait for the window to be ready
        pyautogui.typewrite(text)  # Type the text
    else:
        print(f'Window titled `{window_name}` not found.')  

# Example usage:
if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python chat.py <window_name> <text>')
        sys.exit(1)
    type_to_window(sys.argv[1], sys.argv[2])