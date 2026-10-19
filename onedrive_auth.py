#!/usr/bin/env python3
"""onedrive_auth.py — fully automated OneDrive (personal/MSA) OAuth onboarding.

Drives rclone's OAuth flow end-to-end with a Playwright-controlled Chromium:
  1. starts `rclone authorize onedrive --auth-no-open-browser`
  2. opens the printed auth URL in the headless browser
  3. logs in with the stored credentials (never echoed to stdout/log)
  4. handles "Stay signed in?" and consent pages
  5. waits for rclone to receive the code and emit the token JSON
  6. configures the rclone remote `onedrive` and verifies quota

Exit codes:
  0 success
  2 blocked by MFA / identity verification (manual step required)
  3 selector/flow timeout
  4 rclone error
  5 credential rejected (wrong password / account issue)

Screenshots of every step land in ./onedrive_auth_shots/.
Run with:  .venv/bin/python onedrive_auth.py
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
LOG = HOME / "tools/cloud_backup/onedrive_auth.log"
PASS = CREDS["pass"]
USER = CREDS["user"]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{int(time.time())}_{name}.png"))
    except Exception:
        pass


def wait_any(page, selectors, timeout_ms=1500):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return sel
            except Exception:
                pass
        page.wait_for_timeout(300)
    return None


def click_any(page, selectors, timeout_ms=8000):
    sel = wait_any(page, selectors, timeout_ms)
    if not sel:
        return None
    try:
        page.click(sel, timeout=4000)
        return sel
    except Exception:
        try:
            page.evaluate("s => document.querySelector(s).click()", sel)
            return sel
        except Exception:
            return None


def fill_first(page, selectors, value, timeout_ms=1500):
    sel = wait_any(page, selectors, timeout_ms)
    if not sel:
        return None
    try:
        page.fill(sel, value)
        return sel
    except Exception:
        return None


def main():
    log("=== onedrive_auth start ===")
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
        log("rclone: " + line.strip()[:200])
        m = re.search(r"(http://127\.0\.0\.1:\d+/auth\?state=\S+)", line)
        if m:
            url = m.group(1)
            break
    if not url:
        log("FATAL: no auth URL from rclone")
        return 4
    log("auth url acquired")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900}, locale="en-US")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        shot(page, "01_landing")
        log("landing: " + page.url[:120])

        done = False
        for step in range(45):
            if "127.0.0.1" in page.url and "code=" in page.url:
                done = True
                break
            body = ""
            try:
                body = (page.inner_text("body") or "")[:4000]
            except Exception:
                pass
            low = (body + " " + page.url).lower()

            if any(k in low for k in [
                    "verify your identity", "verify your email", "enter code", "enter the code",
                    "authenticator", "approve sign in", "help us protect", "confirm your identity",
                    "we need to verify", "send a code", "more information required"]):
                shot(page, "BLOCKER_verify")
                log("BLOCKED: verification step required")
                browser.close()
                proc.terminate()
                return 2

            if any(k in low for k in ["incorrect", "account is locked", "your account or password"]):
                shot(page, "BLOCKER_creds")
                log("BLOCKED: credential rejection message shown")
                browser.close()
                proc.terminate()
                return 5

            if fill_first(page, ["input[type=email]", "#i0116"], USER):
                click_any(page, ["#idSIButton9", "input[type=submit]", "button:has-text('Next')"])
                page.wait_for_timeout(1800)
                shot(page, f"02_email_{step}")
                log("email submitted")
                continue

            if fill_first(page, ["input[type=password]", "#i0118"], PASS):
                click_any(page, ["#idSIButton9", "input[type=submit]", "button:has-text('Sign in')"])
                page.wait_for_timeout(2500)
                shot(page, f"03_password_{step}")
                log("password submitted")
                continue

            if click_any(page, ["#idSIButton9", "button:has-text('Yes')", "#idBtn_Back",
                                "button:has-text('No')"], timeout_ms=1500):
                page.wait_for_timeout(1500)
                shot(page, f"04_stay_{step}")
                log("stay-signed-in handled")
                continue

            if click_any(page, ["#idBtn_Accept", "button:has-text('Accept')", "input[value='Yes']",
                                "button:has-text('Yes')", "#idSIButton9"], timeout_ms=1500):
                page.wait_for_timeout(1800)
                shot(page, f"05_consent_{step}")
                log("consent handled")
                continue

            page.wait_for_timeout(1000)

        shot(page, "06_final")
        log("final url: " + page.url[:160])
        browser.close()

    log("waiting for rclone to mint token...")
    try:
        out = proc.communicate(timeout=60)[0] or ""
    except subprocess.TimeoutExpired:
        proc.terminate()
        log("FATAL: rclone did not finish after browser flow")
        return 4

    m = re.search(r"---\>\s*(\{.*?\})\s*\<---End paste", out, re.S)
    if not m:
        m = re.search(r"(\{[^\n]*\"access_token\"[^\n]*\})", out)
    if not m:
        log("FATAL: no token JSON in rclone output:\n" + out[-500:])
        return 4
    token = m.group(1).strip()
    tfile = HOME / ".config/onedrive/rclone_token.json"
    tfile.write_text(token)
    os.chmod(tfile, 0o600)
    log(f"token JSON captured ({len(token)} chars) -> {tfile}")

    r = subprocess.run([RCLONE, "config", "create", "onedrive", "onedrive",
                        f"token={token}", "--non-interactive"], capture_output=True, text=True)
    log("config create rc=%s %s" % (r.returncode, (r.stderr or r.stdout)[:200]))
    r2 = subprocess.run([RCLONE, "about", "onedrive:"], capture_output=True, text=True)
    log("about rc=%s" % r2.returncode)
    print(r2.stdout or r2.stderr)
    return 0 if r2.returncode == 0 else 4


if __name__ == "__main__":
    import atexit

    def _reap():
        subprocess.run(["pkill", "-f", "rclone authorize"], capture_output=True)

    atexit.register(_reap)
    sys.exit(main())
