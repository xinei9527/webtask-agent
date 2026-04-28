from __future__ import annotations

import time
from typing import Any

from playwright.async_api import Page


async def observe_page(page: Page) -> dict[str, Any]:
    start = time.time()
    title = await page.title()
    url = page.url

    body_text = ""
    try:
        body_text = await page.locator("body").inner_text(timeout=3000)
        body_text = body_text[:3000]
    except Exception:
        body_text = ""

    async def safe_eval(selector: str, script: str) -> list[Any]:
        try:
            return await page.locator(selector).evaluate_all(script)
        except Exception:
            return []

    links = await safe_eval(
        "a",
        """els => els.slice(0, 20).map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href
        })).filter(x => x.text || x.href)""",
    )
    buttons = await safe_eval(
        "button, input[type='button'], input[type='submit']",
        """els => els.slice(0, 20).map(b => (
            b.innerText || b.value || b.getAttribute('aria-label') || ''
        ).trim()).filter(Boolean)""",
    )
    inputs = await safe_eval(
        "input, textarea, select",
        """els => els.slice(0, 20).map(i => ({
            tag: i.tagName.toLowerCase(),
            type: i.type || '',
            name: i.name || '',
            id: i.id || '',
            placeholder: i.placeholder || '',
            ariaLabel: i.getAttribute('aria-label') || ''
        }))""",
    )

    return {
        "title": title,
        "url": url,
        "body_text": body_text,
        "links": links,
        "buttons": buttons,
        "inputs": inputs,
        "cost_ms": int((time.time() - start) * 1000),
    }
