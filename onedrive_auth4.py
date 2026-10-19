#!/usr/bin/env python3
"""onedrive_auth4.py — v4: "…" menu path to credential picker + WebAuthn-stub fallback.

Phase A: normal context. After email, if the passkey (fido) page appears, click the
         "..." (#moreOptions) button, dump the menu, and click any entry offering
         another sign-in path ("Sign in another way", "Use your password", etc.).
Phase B: context with WebAuthn stubbed to reject immediately (navigator.credentials
         forced to fail) — forces fallbacks on pages that hinge on FIDO capability.
Completes password/KMSI/consent flow and mints the rclone token when possible.

Exit: 0 ok · 2 blocked · 4 rclone error
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
RCLONE = str(HOME / "tools/bin/rclone")
CREDS = json.load(open(HOME / ".config/onedrive/credentials.json"))
SHOTS = HOME / "tools/cloud_backup/onedrive_auth_shots"
SHOTS.mkdir(parents=True, exist_ok=True)
LOG = HOME / "tools/cloud_backup/onedrive_auth4.log"
PASS_ = CREDS["pass"]
USER = CREDS["user"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

STUB_JS = """
(() => {
  try {
    const bad = {
      get() { return Promise.reject(new DOMException('NotAllowedError', 'NotAllowedError')); },
      create() { return Promise.reject(new DOMException('NotSupportedError', 'NotSupportedError')); },
      store() { return Promise.reject(new Error('unsupported')); },
      preventSilentAccess() { return Promise.reject(new Error('unsupported')); }
    };
    Object.defineProperty(navigator, 'credentials', { get: () => bad, configurable: true });
  } catch (e) {}
})();
"""

MENU_ITEMS = [
    "text=Sign in another way",
    "text=Other ways to sign in",
    "text=Use your password",
    "text=Use your password instead",
    "text=Use a password instead",
    "text=Sign in with your password",
    "text=Use a different sign-in method",
    "text=Use a different method",
    "text=Password",
    "text=Cancel",
    "[role='menuitem']",
]

ALT_LINKS = [
    "a:has-text('another way')",
    "a:has-text('Other ways')",
    "a:has-text('other ways')",
    "a:has-text('password instead')",
    "a:has-text('Use your password')",
    "a:has-text('Use a password')",
    "a:has-text('Use password')",
    "button:has-text('another way')",
    "button:has-text('Use your password')",
    "[id*='SwitchToPassword' i]",
    "[id*='SwitchToCredPicker' i]",
    "[id*='CredPicker' i]",
]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{int(time.time())}_v4_{name}.png"))
    except Exception:
        pass


def dump(page, tag):
    try:
        (SHOTS / f"{int(time.time())}_v4_{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def click(page, sels, timeout_ms=1500):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        for s in sels:
            try:
                el = page.query_selector(s)
                if el and el.is_visible():
                    el.click(timeout=2500)
                    return s
            except Exception:
                pass
        page.wait_for_timeout(200)
    return None


def visible(page, sels, timeout_ms=1200):
    return click.__wrapped__(page, sels, timeout_ms) if False else None  # placeholder


def el_visible(page, sels, timeout_ms=1200):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        for s in sels:
            try:
                el = page.query_selector(s)
                if el and el.is_visible():
                    return s
            except Exception:
                pass
        page.wait_for_timeout(200)
    return None


def drive_flow(page, tag):
    """One pass over the page until it stops changing. Returns 'blocked'|'done'|'progress'."""
    seen = {}
    for step in range(30):
        if "127.0.0.1" in page.url and "code=" in page.url:
            log(f"[{tag}] redirect with code received")
            return "done"
        try:
            body = page.inner_text("body") or ""
        except Exception:
            body = ""
        low = body.lower()[:6000]
        sig = (page.url.split("?")[0][:90], re.sub(r"\W+", "", low)[:120])
        n = seen.get(sig, 0) + 1
        seen[sig] = n
        if n == 1:
            shot(page, f"{tag}_s{step}")
            dump(page, f"{tag}_s{step}")
            log(f"[{tag}] s{step}: {page.url[:100]}")

        # passkey wall?
        if ("fido" in page.url or "face, fingerprint" in low or "security key" in low):
            if n == 1:
                if click(page, ["#moreOptions", "[aria-label*='More' i]"], timeout_ms=2500):
                    page.wait_for_timeout(2000)
                    shot(page, f"{tag}_menu")
                    dump(page, f"{tag}_menu")
                    log(f"[{tag}] menu opened")
                    item = click(page, MENU_ITEMS, timeout_ms=2500)
                    if item:
                        page.wait_for_timeout(3000)
                        shot(page, f"{tag}_menuitem")
                        dump(page, f"{tag}_menuitem")
                        log(f"[{tag}] menu item clicked: {item}")
                        continue
                    log(f"[{tag}] no menu item matched")
            if n >= 3:
                # try alt links as last resort
                if click(page, ALT_LINKS, timeout_ms=1200):
                    page.wait_for_timeout(2500)
                    log(f"[{tag}] alt link clicked")
                    continue
                log(f"[{tag}] passkey wall persists (state x{n})")
                return "blocked"
            page.wait_for_timeout(1500)
            continue

        # normal states
        em = page.query_selector("input[type=email], #i0116")
        if em and em.is_visible():
            try:
                page.fill("input[type=email], #i0116", USER)
            except Exception:
                pass
            if click(page, ["#idSIButton9", "input[type=submit]", "button:has-text('Next')"],
                     timeout_ms=2500):
                page.wait_for_timeout(2600)
                log(f"[{tag}] email submitted")
                continue
        pw = page.query_selector("input[type=password], #i0118")
        if pw and pw.is_visible():
            try:
                page.fill("input[type=password], #i0118", PASS_)
            except Exception:
                pass
            if click(page, ["#idSIButton9", "input[type=submit]", "button:has-text('Sign in')"],
                     timeout_ms=2500):
                page.wait_for_timeout(3000)
                shot(page, f"{tag}_password")
                log(f"[{tag}] password submitted")
                continue
        if "stay signed in" in low or "remain signed in" in low:
            if click(page, ["#idSIButton9", "button:has-text('Yes')"], timeout_ms=2000):
                page.wait_for_timeout(1800)
                log(f"[{tag}] KMSI yes")
                continue
        if "accept" in low or "permissions" in low or "consent" in low:
            if click(page, ["#idBtn_Accept", "button:has-text('Accept')",
                            "input[value='Accept']", "input[value='Yes']", "#idSIButton9"],
                     timeout_ms=2000):
                page.wait_for_timeout(2200)
                log(f"[{tag}] consent handled")
                continue
        if click(page, ALT_LINKS, timeout_ms=900):
            page.wait_for_timeout(2200)
            log(f"[{tag}] alt link clicked (generic)")
            continue
        c = click(page, ["#idSIButton9", "button:has-text('Continue')",
                         "button:has-text('Next')", "input[type=submit]"], timeout_ms=900)
        if c:
            page.wait_for_timeout(1500)
            log(f"[{tag}] generic click ({c})")
            continue
        page.wait_for_timeout(1200)
    return "progress"


def main():
    log("=== onedrive_auth4 start ===")
    proc = subprocess.Popen(
        [RCLONE, "authorize", "onedrive", "--auth-no-open-browser"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    url = None
    t0 = time.time()
    while time.time() - t0 < 60:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = re.search(r"(http://127\.0\.0\.1:\d+/auth\?state=\S+)", line)
        if m:
            url = m.group(1)
            break
    if not url:
        log("FATAL: no auth URL")
        return 4
    log("auth url acquired")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])

        # Phase A — menu path
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                                  locale="en-US")
        page = ctx.new_page()
        page.set_default_timeout(6000)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        r = drive_flow(page, "A")
        log(f"phase A result: {r}")
        ctx.close()

        # Phase B — WebAuthn stub
        if r != "done":
            log("phase B: WebAuthn stubbed context")
            ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                                      locale="en-US")
            ctx.add_init_script(STUB_JS)
            page = ctx.new_page()
            page.set_default_timeout(6000)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            r2 = drive_flow(page, "B")
            log(f"phase B result: {r2}")
            ctx.close()

        browser.close()

    log("waiting for rclone to mint token...")
    try:
        out = proc.communicate(timeout=45)[0] or ""
    except subprocess.TimeoutExpired:
        proc.terminate()
        log("rclone did not finish — blocked")
        return 2

    m = re.search(r"---\>\s*(\{.*?\})\s*\<---End paste", out, re.S)
    if not m:
        m = re.search(r"(\{[^\n]*\"access_token\"[^\n]*\})", out)
    if not m:
        log("no token (blocked, as expected)")
        return 2

    token = m.group(1).strip()
    tfile = HOME / ".config/onedrive/rclone_token.json"
    tfile.write_text(token)
    os.chmod(tfile, 0o600)
    r = subprocess.run([RCLONE, "config", "create", "onedrive", "onedrive",
                        f"token={token}", "--non-interactive"],
                       capture_output=True, text=True)
    log("config create rc=%s" % r.returncode)
    r2 = subprocess.run([RCLONE, "about", "onedrive:"], capture_output=True, text=True)
    log("about rc=%s" % r2.returncode)
    print(r2.stdout or r2.stderr)
    return 0 if r2.returncode == 0 else 4


if __name__ == "__main__":
    import atexit

    def _reap():
        subprocess.run(["pkill", "-f", "rclone authori[z]e"], capture_output=True)

    atexit.register(_reap)
    sys.exit(main())
