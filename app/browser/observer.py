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
    actionable_elements = await safe_eval(
        "a, button, input, textarea, select, [role='button'], [role='link']",
        """
        els => {
            const cssEscape = value => {
                if (window.CSS && CSS.escape) return CSS.escape(value);
                return String(value).replace(/["\\\\]/g, '\\\\$&');
            };
            const textOf = el => (
                el.innerText ||
                el.value ||
                el.getAttribute('aria-label') ||
                el.getAttribute('placeholder') ||
                el.name ||
                el.id ||
                ''
            ).trim();
            const selectorOf = el => {
                const tag = el.tagName.toLowerCase();
                if (el.id) return `#${cssEscape(el.id)}`;
                if (el.name) return `${tag}[name="${cssEscape(el.name)}"]`;
                if (el.getAttribute('aria-label')) {
                    return `${tag}[aria-label="${cssEscape(el.getAttribute('aria-label'))}"]`;
                }
                if (el.getAttribute('placeholder')) {
                    return `${tag}[placeholder="${cssEscape(el.getAttribute('placeholder'))}"]`;
                }
                return tag;
            };
            return els
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none';
                })
                .slice(0, 40)
                .map((el, index) => ({
                    index,
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || el.tagName.toLowerCase(),
                    text: textOf(el).slice(0, 120),
                    selector: selectorOf(el),
                    href: el.href || '',
                    type: el.type || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    ariaLabel: el.getAttribute('aria-label') || ''
                }));
        }
        """,
    )

    return {
        "title": title,
        "url": url,
        "body_text": body_text,
        "links": links,
        "buttons": buttons,
        "inputs": inputs,
        "actionable_elements": actionable_elements,
        "cost_ms": int((time.time() - start) * 1000),
    }
