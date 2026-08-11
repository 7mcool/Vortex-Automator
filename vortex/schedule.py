"""Étape 10 (programmation) — créneaux de publication.

5 créneaux/jour configurables, fuseau horaire géré par zoneinfo
(fini le `(heure-1)%24` codé en dur, faux en heure d'été).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import Config
from .db import Database


def rfc3339_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def immediate_slots(count: int, espacement_min: int = 20,
                    now: datetime | None = None) -> list[datetime]:
    """Créneaux rapprochés à partir de maintenant, pour le contenu d'actualité.

    Une conférence qui vient de se tenir n'attend pas trois jours que la grille
    habituelle se libère : elle intéresse le public MAINTENANT. On espace tout
    de même les mises en ligne, sinon YouTube voit une rafale et la traite
    comme de la publication de masse.
    """
    depart = (now or datetime.now(timezone.utc)) + timedelta(minutes=6)
    return [depart + timedelta(minutes=espacement_min * i) for i in range(count)]


def _reservations_par_jour(db: Database, tz: ZoneInfo) -> dict:
    """Nombre de vidéos déjà calées, par JOUR local — quelle que soit l'heure.

    Compter uniquement les réservations tombant sur une heure de la grille
    laissait passer tout le reste : après un changement de grille (8 créneaux
    aux heures paires → 6 créneaux à d'autres heures), les anciennes
    réservations devenaient invisibles et la nouvelle grille ajoutait ses
    créneaux PAR-DESSUS. Mesuré le 31/07/2026 : 13 vidéos dans la journée pour
    une limite fixée à 6.
    """
    compte: dict = {}
    for valeur in db.scheduled_publish_times():
        try:
            moment = datetime.strptime(valeur, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        jour = moment.astimezone(tz).date()
        compte[jour] = compte.get(jour, 0) + 1
    return compte


def next_free_slots(cfg: Config, db: Database, count: int, now: datetime | None = None) -> list[datetime]:
    """Retourne les prochains créneaux libres (datetimes UTC), en respectant
    daily_limit/jour et les créneaux déjà réservés dans la base."""
    tz = ZoneInfo(cfg.timezone)
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    taken = set(db.scheduled_publish_times())
    deja = _reservations_par_jour(db, tz)

    slots: list[datetime] = []
    day = now_local.date()
    guard = 0
    while len(slots) < count and guard < 365:
        guard += 1
        # La limite s'applique à TOUTE la journée, y compris aux vidéos déjà
        # calées hors grille.
        day_count = deja.get(day, 0)
        for hour in sorted(cfg.publish_hours):
            if day_count >= cfg.daily_limit or len(slots) >= count:
                break
            candidate = datetime(day.year, day.month, day.day, hour, 0, tzinfo=tz)
            if candidate <= now_local + timedelta(minutes=30):
                continue  # trop proche ou passé
            key = rfc3339_utc(candidate)
            if key in taken:
                continue  # déjà compté dans `deja`
            slots.append(candidate.astimezone(timezone.utc))
            taken.add(key)
            day_count += 1
        day += timedelta(days=1)
    return slots
