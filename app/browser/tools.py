from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError


CSS_HINTS = ("#", ".", "[", "input", "textarea", "select", "button", "a", "form", "div", "span", "h1", "h2", "h3")


def _looks_like_selector(value: str) -> bool:
    value = value.strip()
    return value.startswith(CSS_HINTS) or " " in value or "=" in value or ":" in value


class BrowserTools:
    def __init__(self, page: Page):
        self.page = page

    async def open_url(self, url: str) -> str:
        target = url.strip()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            target = f"https://{target}"
        await self.page.goto(target, wait_until="domcontentloaded")
        return f"Opened {target}"

    async def click(self, selector_or_text: str) -> str:
        target = selector_or_text.strip()
        errors: list[str] = []

        if _looks_like_selector(target):
            try:
                await self.page.locator(target).first.click()
                return f"Clicked selector: {target}"
            except Exception as exc:
                errors.append(str(exc))

        for locator in (
            self.page.get_by_role("button", name=re.compile(re.escape(target), re.I)),
            self.page.get_by_text(target, exact=False),
            self.page.locator(target) if _looks_like_selector(target) else None,
        ):
            if locator is None:
                continue
            try:
                await locator.first.click()
                return f"Clicked text: {target}"
            except Exception as exc:
                errors.append(str(exc))

        raise RuntimeError(f"Click target not found: {target}. Last error: {errors[-1] if errors else 'none'}")

    async def click_by_text(self, text: str) -> str:
        return await self.click(text)

    async def type_text(self, selector_or_text: str, text: str) -> str:
        target = selector_or_text.strip()
        errors: list[str] = []

        candidates = []
        if _looks_like_selector(target):
            candidates.append(self.page.locator(target))
        candidates.extend(
            [
                self.page.get_by_label(target, exact=False),
                self.page.get_by_placeholder(target, exact=False),
                self.page.locator(target) if _looks_like_selector(target) else None,
            ]
        )

        for locator in candidates:
            if locator is None:
                continue
            try:
                await locator.first.fill(text)
                return f"Typed into {target}: {text}"
            except Exception as exc:
                errors.append(str(exc))

        raise RuntimeError(f"Input target not found: {target}. Last error: {errors[-1] if errors else 'none'}")

    async def type_by_label(self, label: str, value: str) -> str:
        await self.page.get_by_label(label, exact=False).first.fill(value)
        return f"Typed into label {label}: {value}"

    async def type_by_selector(self, selector: str, value: str) -> str:
        await self.page.locator(selector).first.fill(value)
        return f"Typed into selector {selector}: {value}"

    async def select_option(self, selector_or_label: str, value: str) -> str:
        target = selector_or_label.strip()
        errors: list[str] = []
        candidates = []
        if _looks_like_selector(target):
            candidates.append(self.page.locator(target))
        candidates.extend(
            [
                self.page.get_by_label(target, exact=False),
                self.page.locator(target) if _looks_like_selector(target) else None,
            ]
        )

        for locator in candidates:
            if locator is None:
                continue
            try:
                await locator.first.select_option(label=value)
                return f"Selected option label {value} in {target}"
            except Exception as exc:
                errors.append(str(exc))
            try:
                await locator.first.select_option(value=value)
                return f"Selected option value {value} in {target}"
            except Exception as exc:
                errors.append(str(exc))

        raise RuntimeError(f"Select target not found: {target}. Last error: {errors[-1] if errors else 'none'}")

    async def hover(self, selector_or_text: str) -> str:
        target = selector_or_text.strip()
        if _looks_like_selector(target):
            await self.page.locator(target).first.hover()
            return f"Hovered selector: {target}"
        await self.page.get_by_text(target, exact=False).first.hover()
        return f"Hovered text: {target}"

    async def press(self, key: str) -> str:
        await self.page.keyboard.press(key)
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=3000)
        except PlaywrightTimeoutError:
            pass
        return f"Pressed {key}"

    async def wait(self, seconds: float = 1.0) -> str:
        await self.page.wait_for_timeout(int(seconds * 1000))
        return f"Waited {seconds} seconds"

    async def wait_for_text(self, text: str, timeout_ms: int = 8000) -> str:
        await self.page.get_by_text(text, exact=False).first.wait_for(timeout=timeout_ms)
        return f"Waited for text: {text}"

    async def extract_text(self, selector: str = "body") -> str:
        text = await self.page.locator(selector).first.inner_text(timeout=5000)
        return text[:4000]

    async def extract_links(self, selector: str = "a", limit: int = 20) -> list[dict[str, str]]:
        links: list[dict[str, str]] = await self.page.locator(selector).evaluate_all(
            """
            (els, limit) => els.slice(0, limit).map(a => ({
                text: (a.innerText || a.textContent || '').trim(),
                href: a.href || ''
            })).filter(x => x.text && x.href)
            """,
            limit,
        )
        return links

    async def extract_table(self, selector: str = "table", limit: int = 5) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = await self.page.locator(selector).evaluate_all(
            """
            (tables, limit) => tables.slice(0, limit).map((table, tableIndex) => {
                const rows = Array.from(table.querySelectorAll('tr')).map(tr =>
                    Array.from(tr.querySelectorAll('th,td')).map(cell =>
                        (cell.innerText || cell.textContent || '').trim()
                    )
                ).filter(row => row.some(Boolean));
                return { tableIndex, rows };
            }).filter(table => table.rows.length > 0)
            """,
            limit,
        )
        return tables

    async def scroll(self, pixels: int = 800) -> str:
        await self.page.mouse.wheel(0, pixels)
        return f"Scrolled {pixels}px"

    async def go_back(self) -> str:
        await self.page.go_back(wait_until="domcontentloaded")
        return "Went back"

    async def current_page(self) -> dict[str, str]:
        return {
            "title": await self.page.title(),
            "url": self.page.url,
        }

    async def screenshot(self, path: str) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(target), full_page=True)
        return str(target.resolve())
