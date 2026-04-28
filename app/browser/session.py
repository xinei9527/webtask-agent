from __future__ import annotations

from playwright.async_api import Browser, Page, Playwright, async_playwright


class BrowserSession:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    async def start(self, headless: bool = True) -> Page:
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self.page = await self.browser.new_page(viewport={"width": 1366, "height": 900})
        self.page.set_default_timeout(8000)
        return self.page

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        self.page = None
