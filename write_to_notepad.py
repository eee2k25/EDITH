import pyautogui
import time
import sys

# Check if text argument is provided
if len(sys.argv) < 2:
    print("Please provide text to type as a command line argument.")
    sys.exit(1)

text_to_type = sys.argv[1]

# Allow time to switch to Notepad
time.sleep(1)

# Bring the Notepad window to the front
notepad_window = pyautogui.getWindowsWithTitle('Notepad')[0]
notepad_window.activate()

# Type the provided text into Notepad
pyautogui.typewrite(text_to_type)