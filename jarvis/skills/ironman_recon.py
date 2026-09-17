import os
import base64
import requests
from jarvis.skills.base import Skill

class DownloadIronManSkill(Skill):
    name = "download_ironman"
    description = "Navigates to Google Images, searches for Iron Man, and downloads the first image."

    def execute(self, agent, **kwargs):
        # 1. Bypass the search box and go directly to Google Images results
        search_url = "https://www.google.com/search?tbm=isch&q=Iron+Man+suit"
        agent.browser.open(search_url)
        
        # 2. Wait up to 5 seconds for the image grid to render
        agent.browser.wait_for("img", timeout=5.0)
        
        # 3. Inject JavaScript to extract the raw source of the first result image
        # (We use index 1 to skip the Google logo)
        js_script = "return document.querySelectorAll('img')[1].src;"
        result = agent.browser.execute_js(js_script)
        img_data = result.get("js_result", "")
        
        filepath = os.path.join("logs", "ironman_armor.jpg")
        
        # 4. Decode and save the image (handling both URLs and embedded base64 data)
        if img_data.startswith("data:image"):
            header, encoded = img_data.split(",", 1)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(encoded))
            return {"status": "SUCCESS", "saved_to": filepath}
            
        elif img_data.startswith("http"):
            response = requests.get(img_data)
            with open(filepath, "wb") as f:
                f.write(response.content)
            return {"status": "SUCCESS", "saved_to": filepath}
            
        return {"status": "FAILURE", "reason": "No valid image data found."}

def register():
    return DownloadIronManSkill