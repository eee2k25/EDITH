import pyautogui
import sys
import time
import win32gui


def type_to_window(window_name, text):
    # Find the window by name
    try:
        window = [w for w in pyautogui.getWindows() if window_name.lower() in w.title.lower()]
        if window:
            window[0].activate()  # Bring the window to front
            time.sleep(1)  # Wait for the window to be ready
            pyautogui.typewrite(text)  # Type the text
        else:
            print(f'Window titled `{window_name}` not found.')  
    except Exception as e:
        print(f'An error occurred: {e}') 

# Example usage:
if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python chat.py <window_name> <text>')
        sys.exit(1)
    type_to_window(sys.argv[1], sys.argv[2])