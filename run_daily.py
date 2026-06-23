"""
run_daily.py — Le batch matinal de Brève.

À lancer une fois par jour (cron, ~5h-6h). Il enchaîne :
  1. collecte RSS + regroupement par sujet   (collect.py)
  2. génération des brèves via Claude          (summarize.py)
  3. export du fichier de données              (export.py)

Usage :
    export ANTHROPIC_API_KEY="sk-ant-..."
    python3 run_daily.py --limit 12 --out ./public

Options :
    --limit N         nombre max de brèves (def. 15)
    --min-sources N   sources minimales par brève (def. 2 ; mettez 1 pour
                      autoriser les sujets à source unique)
    --out DOSSIER     où écrire breves.json / breves.js (def. dossier courant)
    --dry-run         collecte seulement, sans appeler Claude (pour tester les flux)
"""

from __future__ import annotations
import argparse
import sys
import datetime as dt

from collect import collect


def main():
    ap = argparse.ArgumentParser(description="Batch quotidien Brève")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--min-sources", type=int, default=2)
    ap.add_argument("--per-theme", type=int, default=6,
                    help="nombre maximum de brèves par thème (def. 6)")
    ap.add_argument("--out", default=".")
    ap.add_argument("--dry-run", action="store_true",
                    help="collecte sans appeler l'IA")
    args = ap.parse_args()

    t0 = dt.datetime.now()
    print(f"[{t0:%H:%M:%S}] Collecte des flux RSS…", file=sys.stderr)
    dossiers = collect(min_outlets=1)
    print(f"  {len(dossiers)} dossiers regroupés "
          f"({sum(1 for d in dossiers if len(d.outlets) >= args.min_sources)} "
          f"avec ≥{args.min_sources} sources)", file=sys.stderr)

    if args.dry_run:
        print("\n--- DRY RUN : aperçu des dossiers (pas d'appel IA) ---")
        for i, d in enumerate(dossiers[:args.limit], 1):
            print(f"[{i}] {d.theme} · {len(d.outlets)} src · {d.lead.title}")
        return

    from summarize import build_breves
    from export import export

    print(f"[{dt.datetime.now():%H:%M:%S}] Génération des brèves via Claude…",
          file=sys.stderr)
    breves = build_breves(dossiers, limit=args.limit,
                          min_sources=args.min_sources, per_theme=args.per_theme)

    if not breves:
        print("Aucune brève générée — vérifiez la clé API et les flux.",
              file=sys.stderr)
        sys.exit(1)

    export(breves, outdir=args.out)
    dt_s = (dt.datetime.now() - t0).total_seconds()
    print(f"[{dt.datetime.now():%H:%M:%S}] Terminé en {dt_s:.0f}s — "
          f"{len(breves)} brèves prêtes.", file=sys.stderr)


if __name__ == "__main__":
    main()
