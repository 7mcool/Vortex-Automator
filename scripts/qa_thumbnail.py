"""Contrôle rapide du rendu de miniature dans le conteneur de production."""

from pathlib import Path

from PIL import Image

from vortex.config import load_config
from vortex.thumbs import _b64, _html_photo, _render_html

photo = Path("/app/assets/portraits/jacques-amessan/amessan-3.jpg")
output = Path("/app/data/qa/thumbnail-uhd.jpg")
output.parent.mkdir(parents=True, exist_ok=True)

html = _html_photo(
    load_config(),
    101,
    "LE SCANDALE DE LA CRUCIFIXION",
    _b64(photo.read_bytes(), "image/jpeg"),
)
if not _render_html(html, output):
    raise SystemExit("Échec du rendu de contrôle")

with Image.open(output) as image:
    width, height = image.size
size = output.stat().st_size
if (width, height) != (3840, 2160):
    raise SystemExit(f"Résolution inattendue : {width}x{height}")
if size > 2_000_000:
    raise SystemExit(f"Fichier trop lourd pour l'API YouTube : {size} octets")
print(f"THUMB_QA={width}x{height} bytes={size}")
