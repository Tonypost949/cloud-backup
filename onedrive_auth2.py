#!/usr/bin/env python3
"""onedrive_auth2.py — v2: handles MSA passkey/FIDO page and offers the password path.

Differences vs v1:
  * never blind-clicks `#idBtn_Back` (v1 did this on the passkey page 44x)
  * explicit passkey-page handler: first looks for "Other ways to sign in" /
    "Use your password" style links, then falls back to Back (max 4 tries)
  * repeat-state detection with clickable inventory dump
  * tighter KMSI handling (only on "stay signed in" body text)

Exit codes: 0 ok · 2 blocked (passkey-only) · 3 flow timeout/loop · 4 rclone · 5 creds
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
LOG = HOME / "tools/cloud_backup/onedrive_auth2.log"
PASS_ = CREDS["pass"]
USER = CREDS["user"]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{int(time.time())}_v2_{name}.png"))
    except Exception:
        pass


def click(page, sels, timeout_ms=1500):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        for s in sels:
            try:
                el = page.query_selector(s)
                if el and el.is_visible():
                    el.click(timeout=3000)
                    return s
            except Exception:
                try:
                    page.evaluate(
                        "s => { const e = document.querySelector(s); if (e) e.click(); }", s)
                    return s
                except Exception:
                    pass
        page.wait_for_timeout(250)
    return None


def dump_clickables(page):
    try:
        return page.evaluate("""() => {
          const out = [];
          document.querySelectorAll("a,button,input[type=submit],div[role=button]").forEach(e => {
            const t = (e.innerText || e.value || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
            if (t && e.offsetParent !== null) out.push(t);
          });
          return out.slice(0, 40);
        }""")
    except Exception:
        return []


FIDO_ALT = [
    "a:has-text('Sign in another way')",
    "a:has-text('Other ways to sign in')",
    "a:has-text('other ways to sign in')",
    "a:has-text('Use your password')",
    "a:has-text('use your password')",
    "a:has-text('Use my password')",
    "a:has-text('password instead')",
    "[id*='SwitchToPassword']",
    "[id*='switchToPassword']",
]

BLOCK_VERIFY = ["verify your identity", "verify your email", "enter code", "enter the code",
                "approve sign in", "help us protect", "confirm your identity", "we need to verify",
                "send a code", "more information required", "text a code", "email a code",
                "use your phone"]
BLOCK_CREDS = ["incorrect", "account is locked", "account or password"]


def main():
    log("=== onedrive_auth2 start ===")
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
        log("rclone: " + line.strip()[:160])
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
        page.set_default_timeout(6000)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        shot(page, "01_landing")
        log("landing: " + page.url[:110])

        seen = {}
        fido_tries = 0
        email_cnt = 0
        done = False
        for step in range(60):
            if "127.0.0.1" in page.url and "code=" in page.url:
                done = True
                log("redirect to localhost with code received")
                break
            try:
                body = page.inner_text("body") or ""
            except Exception:
                body = ""
            low = body.lower()[:6000]
            sig = (page.url.split("?")[0][:90], re.sub(r"\W+", "", low)[:140])
            seen[sig] = seen.get(sig, 0) + 1
            n = seen[sig]
            if n == 1:
                shot(page, f"state{step}")
                log(f"state {step}: {page.url[:100]}")
            if n >= 6:
                log(f"STUCK: same state x{n} url={page.url[:110]}")
                log("clickables: " + json.dumps(dump_clickables(page))[:600])
                shot(page, "STUCK")
                return 3

            if any(k in low for k in BLOCK_VERIFY):
                shot(page, "BLOCKER_verify")
                log("BLOCKED: verification step required")
                browser.close()
                proc.terminate()
                return 2
            if any(k in low for k in BLOCK_CREDS):
                shot(page, "BLOCKER_creds")
                log("BLOCKED: credential rejection message shown")
                browser.close()
                proc.terminate()
                return 5

            is_fido = ("fido" in page.url or "face, fingerprint" in low
                       or "security key" in low or "passkey" in low)
            if is_fido:
                fido_tries += 1
                if n <= 2:
                    log("fido clickables: " + json.dumps(dump_clickables(page))[:500])
                if fido_tries > 4:
                    shot(page, "fido_cap")
                    log("BLOCKED: passkey page persists after 4 tries (passwordless-only account?)")
                    browser.close()
                    proc.terminate()
                    return 2
                alt = click(page, FIDO_ALT, timeout_ms=1800)
                if alt:
                    page.wait_for_timeout(2200)
                    shot(page, f"fido_alt_{step}")
                    log(f"fido: clicked alternative ({alt})")
                    continue
                back = click(page, ["#idBtn_Back", "button:has-text('Back')"], timeout_ms=1800)
                if back:
                    page.wait_for_timeout(2200)
                    shot(page, f"fido_back_{step}")
                    log("fido: clicked Back")
                    continue
                shot(page, "fido_stuck")
                log("BLOCKED: fido page without actionable links")
                browser.close()
                proc.terminate()
                return 2

            em = page.query_selector("input[type=email], #i0116")
            if em and em.is_visible():
                try:
                    page.fill("input[type=email], #i0116", USER)
                except Exception:
                    pass
                if click(page, ["#idSIButton9", "input[type=submit]",
                                "button:has-text('Next')"], timeout_ms=2000):
                    page.wait_for_timeout(2600)
                    shot(page, f"email_{step}")
                    email_cnt += 1
                    log("email submitted")
                    if email_cnt > 3:
                        log("BLOCKED: email loop cap hit")
                        browser.close()
                        proc.terminate()
                        return 3
                    continue

            pw = page.query_selector("input[type=password], #i0118")
            if pw and pw.is_visible():
                try:
                    page.fill("input[type=password], #i0118", PASS_)
                except Exception:
                    pass
                if click(page, ["#idSIButton9", "input[type=submit]",
                                "button:has-text('Sign in')"], timeout_ms=2000):
                    page.wait_for_timeout(3000)
                    shot(page, f"password_{step}")
                    log("password submitted")
                    continue

            if "stay signed in" in low or "remain signed in" in low:
                c = click(page, ["#idSIButton9", "button:has-text('Yes')"], timeout_ms=2000)
                if c:
                    page.wait_for_timeout(1800)
                    shot(page, f"kmsi_{step}")
                    log("KMSI: yes")
                    continue

            if "accept" in low or "permissions" in low or "consent" in low:
                c = click(page, ["#idBtn_Accept", "button:has-text('Accept')",
                                 "input[value='Accept']", "input[value='Yes']",
                                 "#idSIButton9"], timeout_ms=2000)
                if c:
                    page.wait_for_timeout(2200)
                    shot(page, f"consent_{step}")
                    log("consent handled")
                    continue

            c = click(page, ["#idSIButton9", "button:has-text('Continue')",
                             "button:has-text('Next')", "input[type=submit]"], timeout_ms=1200)
            if c:
                page.wait_for_timeout(1500)
                log(f"generic click ({c})")
                continue
            page.wait_for_timeout(1200)

        shot(page, "99_final")
        log("final url: " + page.url[:160])
        browser.close()

    if not done:
        log("flow not completed; waiting briefly for rclone anyway...")

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
        log("FATAL: no token JSON in rclone output:\n" + out[-400:])
        return 4
    token = m.group(1).strip()
    tfile = HOME / ".config/onedrive/rclone_token.json"
    tfile.write_text(token)
    os.chmod(tfile, 0o600)
    log(f"token JSON captured ({len(token)} chars) -> {tfile}")

    r = subprocess.run([RCLONE, "config", "create", "onedrive", "onedrive",
                        f"token={token}", "--non-interactive"],
                       capture_output=True, text=True)
    log("config create rc=%s %s" % (r.returncode, (r.stderr or r.stdout)[:200]))
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
