"""Tableau de bord web (Phase 3) — 100 % stdlib, léger pour le VPS.

    python -m vortex.dashboard          # sert sur 0.0.0.0:8787

Accès protégé par un jeton dans l'URL : http://IP:8787/<DASHBOARD_TOKEN>
(DASHBOARD_TOKEN dans .env — lecture seule, aucune action possible).
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from .config import load_config
from .db import Database

PORT = 8787

PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>Vortex — Sophos PropheTikos</title>
<style>
 body{{font-family:system-ui,sans-serif;background:#0f1220;color:#e8eaf6;margin:0;padding:1rem}}
 h1{{font-size:1.3rem}} h2{{font-size:1rem;color:#9aa4d2;margin-top:1.6rem}}
 .cards{{display:flex;flex-wrap:wrap;gap:.6rem}}
 .card{{background:#1a1f36;border-radius:10px;padding:.7rem 1rem;min-width:7.5rem}}
 .card b{{display:block;font-size:1.5rem}} .card span{{color:#9aa4d2;font-size:.8rem}}
 table{{width:100%;border-collapse:collapse;font-size:.85rem}}
 td,th{{padding:.35rem .5rem;border-bottom:1px solid #2a3050;text-align:left}}
 .ok{{color:#7bd88f}} .warn{{color:#ffcc66}} .err{{color:#ff6b81}}
 footer{{color:#5a6296;font-size:.75rem;margin-top:2rem}}
</style></head><body>
<h1>⚡ Vortex Automator — Sophos PropheTikos</h1>
<div class="cards">{cards}</div>
<h2>📅 Prochaines publications</h2>
<table><tr><th>Quand (UTC)</th><th>Titre</th><th>Habillée</th></tr>{scheduled}</table>
<h2>🕘 Derniers événements</h2>
<table><tr><th>Quand</th><th>Vidéo</th><th>Transition</th><th>Détail</th></tr>{events}</table>
<footer>Actualisation auto toutes les 2 min — généré {now} UTC — lecture seule</footer>
</body></html>"""


def build_page() -> str:
    cfg = load_config()
    db = Database(cfg.db_file)
    try:
        counts = db.counts()
        order = ["DISCOVERED", "TRANSCRIBED", "READY", "SCHEDULED", "PUBLISHED",
                 "FAILED", "BLOCKED", "SKIPPED", "UPLOADING"]
        cards = "".join(
            f'<div class="card"><b>{counts.get(s, 0)}</b><span>{s}</span></div>'
            for s in order if counts.get(s, 0) or s in ("READY", "SCHEDULED", "PUBLISHED"))
        cards += f'<div class="card"><b>{sum(counts.values())}</b><span>TOTAL</span></div>'

        sched = db.conn.execute(
            "SELECT publish_at, title, render_path FROM videos WHERE state='SCHEDULED' "
            "ORDER BY publish_at LIMIT 12").fetchall()
        scheduled = "".join(
            f"<tr><td>{html.escape(r['publish_at'] or '?')}</td>"
            f"<td>{html.escape((r['title'] or '')[:70])}</td>"
            f"<td>{'✅' if r['render_path'] else '—'}</td></tr>"
            for r in sched) or "<tr><td colspan=3>aucune</td></tr>"

        evs = db.conn.execute(
            "SELECT e.at, v.name, e.from_state, e.to_state, e.detail FROM events e "
            "JOIN videos v ON v.id=e.video_id ORDER BY e.id DESC LIMIT 15").fetchall()
        def cls(to):
            return "err" if to in ("FAILED", "BLOCKED") else ("ok" if to in ("SCHEDULED", "PUBLISHED", "READY") else "")
        events = "".join(
            f"<tr><td>{html.escape(r['at'])}</td><td>{html.escape(r['name'][:28])}…</td>"
            f"<td class='{cls(r['to_state'])}'>{html.escape(str(r['from_state']))} → {html.escape(r['to_state'])}</td>"
            f"<td>{html.escape((r['detail'] or '')[:60])}</td></tr>"
            for r in evs) or "<tr><td colspan=4>aucun</td></tr>"

        return PAGE.format(cards=cards, scheduled=scheduled, events=events,
                           now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    finally:
        db.close()


def _media_token() -> str:
    # Jeton d'URL pour servir les clips à Meta (Reels IG) — non devinable.
    return os.environ.get("MEDIA_TOKEN", "") or os.environ.get("DASHBOARD_TOKEN", "")


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):  # noqa: N802
        if not self._serve_media(head=True):
            self.send_response(404)
            self.end_headers()

    def _serve_media(self, head: bool) -> bool:
        """Sert un clip depuis data/exports pour l'API Reels Instagram (URL publique).
        Chemin : /media/<MEDIA_TOKEN>/<fichier.mp4>. Protégé contre la traversée,
        supporte les requêtes Range (206) car Meta télécharge la vidéo par plages."""
        mt = _media_token()
        prefix = f"/media/{mt}/"
        if not mt or not self.path.startswith(prefix):
            return False
        # Décoder les %XX de l'URL : les noms de clips contiennent des accents
        # (é → %C3%A9) et Meta encode le chemin en récupérant la vidéo.
        name = os.path.basename(unquote(self.path[len(prefix):].split("?")[0]))
        try:
            cfg = load_config()
            base = (cfg.data_dir / "exports").resolve()
            fpath = (base / name).resolve()
            if base != fpath.parent or not fpath.is_file():
                self.send_response(404); self.end_headers(); return True
        except Exception:
            self.send_response(404); self.end_headers(); return True
        size = fpath.stat().st_size
        ctype = "video/mp4" if name.lower().endswith(".mp4") else "application/octet-stream"
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng.strip())
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416); self.end_headers(); return True
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not head:
            try:
                with open(fpath, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(262144, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
        return True

    def do_GET(self):  # noqa: N802
        if self._serve_media(head=False):
            return
        token = os.environ.get("DASHBOARD_TOKEN", "")
        if not token or self.path.strip("/") not in (token, f"{token}/api"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            if self.path.strip("/").endswith("/api"):
                cfg = load_config()
                db = Database(cfg.db_file)
                body = json.dumps(db.counts(), ensure_ascii=False).encode()
                db.close()
                ctype = "application/json"
            else:
                body = build_page().encode()
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # jamais de crash du serveur
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(exc).encode())

    def log_message(self, *args):  # silencieux
        pass


def main() -> None:
    from .config import load_env
    load_env()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Tableau de bord sur :{PORT} (jeton requis dans l'URL)")
    server.serve_forever()


if __name__ == "__main__":
    main()
