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


def next_free_slots(cfg: Config, db: Database, count: int, now: datetime | None = None) -> list[datetime]:
    """Retourne les prochains créneaux libres (datetimes UTC), en respectant
    daily_limit/jour et les créneaux déjà réservés dans la base."""
    tz = ZoneInfo(cfg.timezone)
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    taken = set(db.scheduled_publish_times())

    slots: list[datetime] = []
    day = now_local.date()
    guard = 0
    while len(slots) < count and guard < 365:
        guard += 1
        day_count = 0
        for hour in sorted(cfg.publish_hours):
            if day_count >= cfg.daily_limit or len(slots) >= count:
                break
            candidate = datetime(day.year, day.month, day.day, hour, 0, tzinfo=tz)
            if candidate <= now_local + timedelta(minutes=30):
                continue  # trop proche ou passé
            key = rfc3339_utc(candidate)
            if key in taken:
                day_count += 1
                continue
            slots.append(candidate.astimezone(timezone.utc))
            taken.add(key)
            day_count += 1
        day += timedelta(days=1)
    return slots
