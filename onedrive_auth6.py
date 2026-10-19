#!/usr/bin/env python3
"""onedrive_auth6.py — v6: fixed on-screen guards + email branch restored.

v5 bug: MSA pages pre-render the password input off-screen
(<input id="i0118" class="moveOffScreen" aria-hidden="true">), so the password
branch fired on the email page and spun on validation errors. v6:
  * vis() helper: element must be visible, not aria-hidden, not moveOffScreen,
    have an on-screen bounding box.
  * email branch restored (fill #i0116 -> Next) BEFORE password branch.
  * fido -> #moreOptions -> "Sign in another way" -> options -> "Use your password"
    -> password -> KMSI -> consent -> token (v4-validated chain).
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
LOG = HOME / "tools/cloud_backup/onedrive_auth6.log"
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


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{int(time.time())}_v6_{name}.png"))
    except Exception:
        pass


def dump(page, tag):
    try:
        (SHOTS / f"{int(time.time())}_v6_{tag}.html").write_text(
            page.content(), encoding="utf-8")
    except Exception:
        pass


def vis(page, sel):
    """Return element only if genuinely on-screen (not moved off-screen)."""
    try:
        el = page.query_selector(sel)
        if not el or not el.is_visible():
            return None
        if (el.get_attribute("aria-hidden") or "").lower() == "true":
            return None
        cls = el.get_attribute("class") or ""
        if "moveOffScreen" in cls:
            return None
        box = el.bounding_box()
        if not box or box["width"] < 5 or box["height"] < 5:
            return None
        if box["x"] < -100 or box["y"] < -100:
            return None
        return el
    except Exception:
        return None


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


def click_text(page, text, timeout_ms=2000):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        try:
            el = page.get_by_text(text, exact=True).first
            if el and el.is_visible():
                el.click(timeout=2500)
                return True
        except Exception:
            pass
        page.wait_for_timeout(200)
    return False


def drive(page):
    seen = {}
    for step in range(60):
        if "127.0.0.1" in page.url and "code=" in page.url:
            return "done"
        try:
            body = page.inner_text("body") or ""
        except Exception:
            body = ""
        low = body.lower()[:8000]
        url = page.url
        sig = (url.split("?")[0][:90], re.sub(r"\W+", "", low)[:130])
        seen[sig] = seen.get(sig, 0) + 1
        n = seen[sig]
        if n == 1:
            shot(page, f"s{step}")
            dump(page, f"s{step}")
            log(f"s{step}: {url[:110]}")
        if n >= 8:
            shot(page, "stuck")
            dump(page, "stuck")
            log(f"stuck at {url[:110]} (state x{n})")
            return "blocked"

        # 1. FIDO page (or its error overlay) — surface "Sign in another way"
        if "fido" in url:
            if n <= 2 and click(page, ["#moreOptions"], timeout_ms=2000):
                page.wait_for_timeout(2500)
                shot(page, f"fido_more_{step}")
                log("fido: moreOptions clicked")
            if click(page, ["text=Sign in another way",
                            "button:has-text('Sign in another way')",
                            "a:has-text('Sign in another way')"], timeout_ms=2500):
                page.wait_for_timeout(3000)
                shot(page, f"fido_another_{step}")
                log("fido: clicked 'Sign in another way'")
                continue
            page.wait_for_timeout(1500)
            continue

        # 2. options page — "Use your password"
        opts = vis(page, "[aria-label='Use your password']")
        if opts:
            if click(page, ["[aria-label='Use your password'] span[role=button]",
                            "[aria-label='Use your password']",
                            "text=Use your password"], timeout_ms=2500):
                page.wait_for_timeout(3200)
                shot(page, f"use_password_{step}")
                log("options: clicked 'Use your password'")
                continue

        # 3. error page elsewhere — "Sign in another way"
        if "sign you in" in low and "passkey" in low:
            if click(page, ["text=Sign in another way",
                            "a:has-text('Sign in another way')",
                            "span:has-text('Sign in another way')"], timeout_ms=2200):
                page.wait_for_timeout(3000)
                log("error page: clicked 'Sign in another way'")
                continue

        # 4. email entry (restored; guarded)
        em = vis(page, "input[type=email], #i0116")
        if em:
            try:
                page.fill("input[type=email], #i0116", USER)
            except Exception:
                pass
            if click(page, ["#idSIButton9", "input[type=submit]",
                            "button:has-text('Next')"], timeout_ms=2500):
                page.wait_for_timeout(2600)
                log("email submitted")
                continue

        # 5. password entry (guarded — only genuinely on-screen fields)
        pw = vis(page, "input[type=password], #i0118")
        if pw:
            try:
                page.fill("input[type=password], #i0118", PASS_)
            except Exception:
                pass
            if click(page, ["#idSIButton9", "input[type=submit]",
                            "button:has-text('Sign in')", "button:has-text('Continue')"],
                     timeout_ms=2500):
                page.wait_for_timeout(3500)
                shot(page, f"password_{step}")
                log("password submitted")
                continue

        # 6. KMSI
        if "stay signed in" in low or "remain signed in" in low:
            if click(page, ["#idSIButton9", "button:has-text('Yes')"], timeout_ms=2000):
                page.wait_for_timeout(2000)
                log("KMSI: yes")
                continue

        # 7. security-info nags (defer)
        if any(k in low for k in ["keep your account secure", "protect your account",
                                  "add security info", "don't lose access",
                                  "secure your account", "let's protect"]):
            if click_text(page, "Not now", timeout_ms=1500) or \
               click_text(page, "Skip for now", timeout_ms=1500) or \
               click_text(page, "Maybe later", timeout_ms=1500):
                page.wait_for_timeout(2500)
                log("security-info nag: deferred")
                continue

        # 8. verification / credential walls
        if any(k in low for k in ["help us protect", "verify your identity", "we need to verify",
                                  "enter the code", "incorrect password", "account or password",
                                  "your account has been locked"]):
            shot(page, f"wall_{step}")
            dump(page, f"wall_{step}")
            log(f"verification/credential wall detected at {url[:100]}")
            return "blocked"

        # 9. consent
        if "accept" in low or "permissions" in low or "consent" in low:
            if click(page, ["#idBtn_Accept", "button:has-text('Accept')",
                            "input[value='Accept']", "input[value='Yes']", "#idSIButton9"],
                     timeout_ms=2000):
                page.wait_for_timeout(2500)
                log("consent handled")
                continue

        # 10. generic
        c = click(page, ["#idSIButton9", "button:has-text('Continue')",
                         "button:has-text('Next')", "button:has-text('Sign in')",
                         "input[type=submit]"], timeout_ms=1000)
        if c:
            page.wait_for_timeout(1800)
            log(f"generic click ({c})")
            continue
        page.wait_for_timeout(1200)
    return "progress"


def main():
    log("=== onedrive_auth6 start ===")
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
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                                  locale="en-US")
        ctx.add_init_script(STUB_JS)
        page = ctx.new_page()
        page.set_default_timeout(6000)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        r = drive(page)
        log(f"drive result: {r}")
        shot(page, "99_final")
        log("final url: " + page.url[:160])
        browser.close()

    log("waiting for rclone to mint token...")
    try:
        out = proc.communicate(timeout=60)[0] or ""
    except subprocess.TimeoutExpired:
        proc.terminate()
        log("rclone did not finish — blocked")
        return 2

    m = re.search(r"--->\s*(\{.*?\})\s*<---End paste", out, re.S)
    if not m:
        m = re.search(r"(\{[^\n]*\"access_token\"[^\n]*\})", out)
    if not m:
        log("no token (blocked, as expected)")
        return 2

    token = m.group(1).strip()
    tfile = HOME / ".config/onedrive/rclone_token.json"
    tfile.write_text(token)
    os.chmod(tfile, 0o600)
    log(f"token captured ({len(token)} chars) -> {tfile}")

    try:
        dumpcfg = json.loads(subprocess.run(
            [RCLONE, "config", "dump"], capture_output=True, text=True).stdout or "{}")
    except Exception:
        dumpcfg = {}
    if "onedrive" in dumpcfg:
        r = subprocess.run([RCLONE, "config", "update", "onedrive", "token", token],
                           capture_output=True, text=True)
    else:
        r = subprocess.run([RCLONE, "config", "create", "onedrive", "onedrive",
                            "token", token, "--non-interactive"],
                           capture_output=True, text=True)
    log("config rc=%s %s" % (r.returncode, (r.stderr or r.stdout).strip()[:200]))

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
