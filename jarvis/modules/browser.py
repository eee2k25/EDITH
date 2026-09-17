"""Dynamic Browser Automation - Connects to existing Edge session."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..config import Settings
from ..exceptions import ActionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.browser")


class BrowserModule(AutomationModule):
    name = "browser"

    def __init__(self, settings: Settings, dry_run_override: bool | None = None) -> None:
        super().__init__(settings, dry_run_override)
        self._driver: Any = None

    def check_capability(self) -> Capability:
        try:
            import selenium
            return Capability(self.name, True, "selenium available")
        except ImportError as exc:
            return Capability(self.name, False, f"missing dependency: {exc}")

    def start(self) -> Any:
        """Connect to your existing Edge session with debug port 9222."""
        if self._driver is not None:
            return self._driver

        from selenium import webdriver
        from selenium.webdriver.edge.options import Options as EdgeOptions

        opts = EdgeOptions()
        opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

        try:
            self._driver = webdriver.Edge(options=opts)
            log.info("Connected to existing Edge session - EEE 2K25 profile")
            print("[BROWSER] Connected to your EEE 2K25 Edge profile")
        except Exception as e:
            log.warning(f"Could not connect to Edge: {e}")
            print(f"[BROWSER] Could not connect to existing Edge: {e}")
            self._driver = None

        return self._driver

    def quit(self) -> None:
        """Do not close Edge - just disconnect."""
        self._driver = None
        print("[BROWSER] Disconnected from Edge. Your browser stays open.")

    def __enter__(self) -> "BrowserModule":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.quit()

    def _d(self) -> Any:
        if self._driver is None:
            self.start()
        return self._driver

    def open(self, url: str) -> dict:
        if self.dry_run:
            return self.shadow("open", url=url)
        d = self._d()
        if d is None:
            return {"error": "No browser connected"}
        d.get(url)
        return {"url": d.current_url, "title": d.title}

    @property
    def current_url(self) -> str:
        if self.dry_run:
            return "dry-run://current"
        d = self._d()
        if d is None:
            return ""
        return d.current_url

    @property
    def title(self) -> str:
        if self.dry_run:
            return "(dry-run)"
        d = self._d()
        if d is None:
            return ""
        return d.title

    def _find(self, selector: str, timeout: float = 10.0):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        d = self._d()
        return WebDriverWait(d, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )

    def click(self, selector: str, timeout: float = 10.0) -> dict:
        if self.dry_run:
            return self.shadow("click", selector=selector)
        el = self._find(selector, timeout)
        el.click()
        return {"clicked": selector}

    def type(self, selector: str, text: str, timeout: float = 10.0,
             clear: bool = True, secret: bool = False) -> dict:
        if self.dry_run:
            return self.shadow("type", selector=selector,
                               text="<redacted>" if secret else text)
        el = self._find(selector, timeout)
        if clear:
            el.clear()
        el.send_keys(text)
        return {"typed_into": selector, "chars": len(text)}

    def submit(self, selector: str = "form", timeout: float = 10.0) -> dict:
        if self.dry_run:
            return self.shadow("submit", selector=selector)
        form = self._find(selector, timeout)
        form.submit()
        return {"submitted": selector, "landed_on": self._d().current_url}

    def text_of(self, selector: str, timeout: float = 10.0) -> str:
        if self.dry_run:
            return "(dry-run text)"
        return self._find(selector, timeout).text

    def scroll(self, pixels: int = 800) -> dict:
        return self.execute_js(f"window.scrollBy(0, {pixels});")

    def execute_js(self, script: str, *args) -> dict:
        if self.dry_run:
            return self.shadow("execute_js", script=script[:120])
        result = self._d().execute_script(script, *args)
        return {"js_result": result}

    def wait_for(self, selector: str, timeout: float = 10.0) -> dict:
        if self.dry_run:
            return self.shadow("wait_for", selector=selector, timeout=timeout)
        self._find(selector, timeout)
        return {"appeared": selector}

    def screenshot(self, path: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("screenshot", path=path)
        target = Path(path or "logs/browser_shot.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        ok = self._d().save_screenshot(str(target))
        if not ok:
            raise ActionError(f"screenshot failed -> {target}")
        return {"screenshot": str(target)}

    def save_cookies(self, path: str = "logs/cookies.json") -> dict:
        if self.dry_run:
            return self.shadow("save_cookies", path=path)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        cookies = self._d().get_cookies()
        p.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        return {"saved": len(cookies), "to": str(p)}

    def load_cookies(self, path: str = "logs/cookies.json") -> dict:
        if self.dry_run:
            return self.shadow("load_cookies", path=path)
        cookies = json.loads(Path(path).read_text(encoding="utf-8"))
        d = self._d()
        for c in cookies:
            c.pop("expiry", None)
            try:
                d.add_cookie(c)
            except Exception as exc:
                log.warning("cookie %s rejected: %s", c.get("name"), exc)
        return {"loaded": len(cookies), "from": path}
