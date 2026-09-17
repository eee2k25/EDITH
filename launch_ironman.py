import os
import base64
import requests
import time
from jarvis.config import Settings
from jarvis.modules.browser import BrowserModule

print("Initiating J.A.R.V.I.S. Iron Man Protocol...")

settings = Settings()
# Force headless mode off so you can physically watch it work!
browser = BrowserModule(settings)
browser.start()

try:
    print("Navigating to DuckDuckGo Images (Bypassing Google's Bot-Blockers)...")
    # DuckDuckGo is much friendlier to scrapers than Google
    browser.open("https://duckduckgo.com/?q=Iron+Man+suit&t=h_&iar=images&iax=images&ia=images")

    # Wait 4 seconds for the grid to render
    time.sleep(4)

    print("Extracting image data...")
    # Smarter JS: Grabs the first image source it can find that isn't a tiny icon
    js_script = """
    let imgs = document.querySelectorAll('img');
    for (let img of imgs) {
        if (img.src && img.src.length > 100 && img.src.includes('http')) {
            return img.src;
        }
    }
    return '';
    """
    result = browser.execute_js(js_script)
    img_data = result.get("js_result", "")

    filepath = os.path.join("logs", "ironman_armor.jpg")
    os.makedirs("logs", exist_ok=True)

    if img_data:
        print(f"Downloading from: {img_data[:60]}...")
        response = requests.get(img_data)
        with open(filepath, "wb") as f:
            f.write(response.content)
        print(f"\nSUCCESS: Armor secured and saved to {filepath}")
    else:
        print("\nMISSION FAILED: No valid image data found.")

finally:
    print("Closing browser session...")
    time.sleep(2) # Pause so you can see it before it closes
    browser.quit()