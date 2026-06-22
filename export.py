"""
export.py — Écrit les brèves dans les formats consommés par l'application.

Produit deux fichiers :
  - breves.json : la revue du jour en JSON (pour une vraie app / API).
  - breves.js   : le même contenu sous forme « const ARTICLES = [...] »,
                  directement compatible avec le prototype HTML actuel.

C'est ce fichier que le batch matinal régénère chaque jour.
"""

from __future__ import annotations
import json
import datetime as dt
from pathlib import Path


def export(breves: list[dict], outdir: str = ".") -> None:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "date_label": _date_label_fr(),
        "count": len(breves),
        "breves": breves,
    }

    (out / "breves.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    js = ("// Généré automatiquement par Brève — ne pas éditer à la main.\n"
          f"// {payload['generated_at']}\n"
          "const ARTICLES = " +
          json.dumps(breves, ensure_ascii=False, indent=2) + ";\n")
    (out / "breves.js").write_text(js, encoding="utf-8")

    print(f"Écrit : {out/'breves.json'} et {out/'breves.js'} ({len(breves)} brèves)")


_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre"]
_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

def _date_label_fr(d: dt.date | None = None) -> str:
    d = d or dt.date.today()
    return f"{_JOURS[d.weekday()].capitalize()} {d.day} {_MOIS[d.month-1]}"
