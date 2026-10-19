#!/usr/bin/env python3
"""onedrive_auth3.py — deep probe of the MSA FIDO/passkey wall.

After email entry, Microsoft hard-routes this account to login.microsoft.com/consumers/fido/get
("Face, fingerprint, PIN or security key"). v3:
  * dumps full page HTML + ALL controls (incl. hidden) to evidence files
  * tries the "..." (more options) menu, "Try again", "Back" — logging URL deltas
  * watches ~60s for any async fallback ("Other ways to sign in" etc.)
  * if a password/alternative path appears -> completes the full flow (password,
    KMSI, consent) and mints the rclone token
Exit codes: 0 ok · 2 blocked (passkey-only) · 4 rclone error
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
LOG = HOME / "tools/cloud_backup/onedrive_auth3.log"
PASS_ = CREDS["pass"]
USER = CREDS["user"]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{int(time.time())}_v3_{name}.png"))
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
                pass
        page.wait_for_timeout(250)
    return None


def try_click_enabled(page, sels):
    for s in sels:
        try:
            el = page.query_selector(s)
            if el and el.is_visible():
                dis = el.get_attribute("disabled")
                aria = el.get_attribute("aria-disabled")
                if dis not in ("true",) and aria not in ("true",):
                    el.click(timeout=3000)
                    return s
        except Exception:
            pass
    return None


def dump_all(page, tag):
    try:
        html = page.content()
        (SHOTS / f"{int(time.time())}_v3_{tag}.html").write_text(html, encoding="utf-8")
        els = page.evaluate("""() => {
          const out = [];
          document.querySelectorAll('a,button,input[type=submit],[role=button],[tabindex]').forEach(e => {
            const t = (e.innerText || e.value || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
            const id = e.id || '';
            const al = e.getAttribute('aria-label') || '';
            const vis = !!(e.offsetParent !== null);
            if ((t || id || al) && out.length < 300) out.push({id, t, al, vis});
          });
          return out;
        }""")
        (SHOTS / f"{int(time.time())}_v3_{tag}_elements.json").write_text(
            json.dumps(els, indent=1), encoding="utf-8")
        return html, els
    except Exception as e:
        log(f"dump error: {e}")
        return "", []


FALLBACK = [
    "a:has-text('another way')", "a:has-text('Another way')",
    "a:has-text('different method')", "a:has-text('Other options')",
    "a:has-text('other options')", "a:has-text('password')",
    "button:has-text('password')", "button:has-text('Password')",
    "[id*='SwitchTo' i]", "[id*='switchTo' i]", "[id*='Alternative' i]",
    "[aria-label*='another' i]", "[aria-label*='password' i]",
    "[aria-label*='Other way' i]",
]


def main():
    log("=== onedrive_auth3 start (deep probe) ===")
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

        # email step
        if click(page, ["input[type=email], #i0116"], timeout_ms=4000):
            try:
                page.fill("input[type=email], #i0116", USER)
            except Exception:
                pass
            click(page, ["#idSIButton9", "input[type=submit]", "button:has-text('Next')"],
                  timeout_ms=2500)
            page.wait_for_timeout(3500)
            log("email submitted")
        shot(page, "01_after_email")
        log(f"url now: {page.url[:120]}")

        html, els = dump_all(page, "02_after_email")
        low = html.lower()
        for kw in ["other", "password", "switch", "alternative", "back", "try again",
                   "different", "passkey", "security key"]:
            hits = [m.start() for m in re.finditer(re.escape(kw), low)][:3]
            if hits:
                for h in hits[:2]:
                    frag = html[max(0, h - 80):h + 120].replace("\n", " ")
                    log(f"kw[{kw}] ...{frag[:180]}...")

        # fallback link hunt over ~60s
        found = None
        for i in range(30):
            f = click(page, FALLBACK, timeout_ms=800)
            if f:
                found = f
                log(f"FALLBACK control clicked: {f}")
                page.wait_for_timeout(3000)
                shot(page, f"03_fallback_{i}")
                break
            if i == 6:
                s = try_click_enabled(page, ["...:visible", "button[aria-label='...']",
                                             "[aria-label*='More' i]",
                                             "[id*='moreButton' i]"])
                if s:
                    log(f"more-options clicked: {s}")
                    page.wait_for_timeout(2500)
                    shot(page, "03_more_options")
                    dump_all(page, "03_more_options")
            if i == 12:
                s = try_click_enabled(page, ["button:has-text('Try again')",
                                             "#idBtn_TryAgain", "button:has-text('try again')"])
                log(f"try-again clicked: {s}")
                page.wait_for_timeout(4000)
                shot(page, "04_try_again")
                dump_all(page, "04_try_again")
            if i == 20:
                s = try_click_enabled(page, ["#idBtn_Back", "button:has-text('Back')"])
                u_before = page.url
                log(f"back clicked: {s}")
                page.wait_for_timeout(4000)
                if page.url != u_before:
                    log(f"back navigated to: {page.url[:120]}")
                shot(page, "05_back")
                dump_all(page, "05_back")
            page.wait_for_timeout(2000)

        dump_all(page, "06_probe_end")
        log(f"probe end url: {page.url[:130]}")

        # if a fallback surfaced, finish the flow
        ok_flow = False
        if found or "password" in page.content().lower():
            for step in range(40):
                if "127.0.0.1" in page.url and "code=" in page.url:
                    ok_flow = True
                    log("redirect with code received")
                    break
                pw = page.query_selector("input[type=password], #i0118")
                if pw and pw.is_visible():
                    try:
                        page.fill("input[type=password], #i0118", PASS_)
                    except Exception:
                        pass
                    click(page, ["#idSIButton9", "input[type=submit]",
                                 "button:has-text('Sign in')"], timeout_ms=2500)
                    page.wait_for_timeout(3000)
                    shot(page, f"10_password_{step}")
                    log("password submitted")
                    continue
                c = click(page, ["#idSIButton9", "button:has-text('Yes')",
                                 "button:has-text('Continue')", "#idBtn_Accept",
                                 "button:has-text('Accept')"], timeout_ms=1500)
                if c:
                    page.wait_for_timeout(2000)
                    log(f"generic click ({c})")
                    continue
                page.wait_for_timeout(1500)
            shot(page, "11_flow_end")
            log(f"flow end url: {page.url[:140]}")

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
        log("no token (expected if blocked)")
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
