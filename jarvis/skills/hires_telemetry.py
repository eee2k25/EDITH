from jarvis.skills.base import Skill

class HiresTelemetrySkill(Skill):
    name = "hires_telemetry"
    description = "Navigates to a weather portal and extracts live solar/wind data."

    def execute(self, agent, **kwargs):
        # 1. Target a URL for renewable energy data
        target_url = "https://example-weather-portal.com"
        
        # 2. Tell the browser to navigate there
        agent.browser.open(target_url)
        
        # 3. Use the parser to extract the page data
        page_data = agent.parser.scrape(target_url)
        
        # 4. (Future) Send the data to the LLM Brain to format as JSON
        
        return {"status": "success", "extracted": page_data}

# Register the skill so the main state machine can find it
def register():
    return HiresTelemetrySkill