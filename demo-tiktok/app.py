"""Sophos Publisher — mini-application web de démonstration pour la review TikTok.

Sert trois routes derrière traefik (https://sophos.hedjav.com) :
  /app       page d'accueil avec le bouton « Log in with TikTok » (Login Kit)
  /callback  échange du code OAuth contre un jeton, affiche le formulaire
  /publish   publie la vidéo de démo via Content Posting API (Direct Post)

Clés lues dans l'environnement : TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET
(celles du bac à sable pendant la review, celles de production ensuite).
"""

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

KEY = os.environ["TIKTOK_CLIENT_KEY"]
SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
REDIRECT = "https://sophos.hedjav.com/callback"
VIDEO_URL = "https://sophos.hedjav.com/demo-clip.mp4"

STATE = {"csrf": None, "token": None, "user": None}

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sophos Publisher</title><style>
body{font-family:system-ui,'Segoe UI',Arial;background:linear-gradient(160deg,#1a1030,#2d1b4e 60%,#0f0a1e);color:#fff;min-height:100vh;margin:0;display:flex;align-items:center;justify-content:center}
.card{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:18px;padding:42px 48px;max-width:540px;text-align:center;box-shadow:0 18px 60px rgba(0,0,0,.45)}
img.logo{width:88px;height:88px;border-radius:20px}
h1{font-size:26px;margin:14px 0 4px}p{color:#cbc3e3;line-height:1.5}
.btn{display:inline-block;margin-top:18px;background:#fe2c55;color:#fff;font-weight:700;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;border:none;cursor:pointer}
input[type=text]{width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:1px solid #555;background:#180f2e;color:#fff;font-size:15px;margin:10px 0}
.ok{color:#7cfc98;font-weight:600}.err{color:#ff8080}
.muted{font-size:13px;color:#8f86ad;margin-top:22px}
code{background:#0d081c;padding:2px 6px;border-radius:5px;font-size:13px}
</style></head><body><div class="card">
<img class="logo" src="https://sophos.hedjav.com/logo-1024.png" alt="Sophos PropheTikos">
<h1>Sophos Publisher</h1>
__BODY__
<p class="muted">Internal tool of the Sophos PropheTikos ministry &mdash; publishes our own
sermon clips to our own TikTok account.</p>
</div></body></html>"""


def _page(body: str) -> bytes:
    return PAGE.replace("__BODY__", body).encode()


def _api(url: str, payload: dict | None, token: str | None = None,
         form: bool = False) -> dict:
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        if form:
            data = urllib.parse.urlencode(payload).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        return {"error": {"code": exc.code, "message": exc.read().decode()[:400]}}


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path)
        if path.path == "/app":
            STATE["csrf"] = secrets.token_urlsafe(16)
            auth = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
                "client_key": KEY,
                "scope": "user.info.basic,video.upload,video.publish",
                "response_type": "code",
                "redirect_uri": REDIRECT,
                "state": STATE["csrf"],
            })
            self._send(_page(
                "<p>Publish the ministry's sermon clips to its TikTok account, "
                "automatically.</p>"
                f'<a class="btn" href="{auth}">Log in with TikTok</a>'))
        elif path.path == "/callback":
            q = urllib.parse.parse_qs(path.query)
            code = (q.get("code") or [""])[0]
            state = (q.get("state") or [""])[0]
            if not code or state != STATE["csrf"]:
                self._send(_page('<p class="err">Invalid OAuth state or missing code.</p>'), 400)
                return
            tok = _api("https://open.tiktokapis.com/v2/oauth/token/", {
                "client_key": KEY, "client_secret": SECRET, "code": code,
                "grant_type": "authorization_code", "redirect_uri": REDIRECT,
            }, form=True)
            if "access_token" not in tok:
                self._send(_page(f'<p class="err">Token exchange failed:</p><code>{json.dumps(tok)[:300]}</code>'), 502)
                return
            STATE["token"] = tok["access_token"]
            info = _api("https://open.tiktokapis.com/v2/user/info/?fields=display_name,avatar_url",
                        None, token=STATE["token"])
            STATE["user"] = (info.get("data", {}).get("user", {}) or {}).get("display_name", "TikTok user")
            self._send(_page(
                f'<p class="ok">Connected as {STATE["user"]} &mdash; authorization granted.</p>'
                '<form method="post" action="/publish">'
                '<input type="text" name="title" value="La volonté de Dieu — extrait (démo)" maxlength="140">'
                '<button class="btn" type="submit" name="mode" value="direct">Direct Post to TikTok</button> '
                '<button class="btn" type="submit" name="mode" value="inbox" style="background:#5b3fd4">Upload to TikTok drafts</button>'
                '</form>'))
        else:
            self._send(_page('<p><a class="btn" href="/app">Open the app</a></p>'), 404)

    def do_POST(self):  # noqa: N802
        if urllib.parse.urlparse(self.path).path != "/publish" or not STATE["token"]:
            self._send(_page('<p class="err">Not authorized yet.</p>'), 400)
            return
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        title = (form.get("title") or ["Sophos PropheTikos"])[0][:140]
        mode = (form.get("mode") or ["direct"])[0]
        if mode == "inbox":
            res = _api("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/", {
                "source_info": {"source": "PULL_FROM_URL", "video_url": VIDEO_URL},
            }, token=STATE["token"])
        else:
            res = _api("https://open.tiktokapis.com/v2/post/publish/video/init/", {
                "post_info": {"title": title, "privacy_level": "SELF_ONLY",
                              "disable_duet": False, "disable_comment": False,
                              "disable_stitch": False},
                "source_info": {"source": "PULL_FROM_URL", "video_url": VIDEO_URL},
            }, token=STATE["token"])
        pid = res.get("data", {}).get("publish_id")
        if not pid:
            self._send(_page(f'<p class="err">Publish failed:</p><code>{json.dumps(res)[:400]}</code>'), 502)
            return
        status = _api("https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                      {"publish_id": pid}, token=STATE["token"])
        st = status.get("data", {}).get("status", "PROCESSING")
        how = ("uploaded to the account's TikTok drafts (video.upload)" if mode == "inbox"
               else "sent via Direct Post (video.publish)")
        self._send(_page(
            f'<p class="ok">Video {how} &#10003;</p>'
            f'<p>publish_id&nbsp;: <code>{pid}</code><br>status&nbsp;: <code>{st}</code></p>'
            '<p>TikTok is downloading and processing the video on the account.</p>'))

    def log_message(self, fmt, *args):  # keep container logs terse
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
