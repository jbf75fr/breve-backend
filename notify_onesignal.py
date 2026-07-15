#!/usr/bin/env python3
"""
notify_onesignal.py : envoie la notification push quotidienne « Votre revue du
jour est prête » à tous les abonnés, via l'API REST de OneSignal.

Appelé en fin de workflow, une fois la revue publiée. La clé API (secrète) et
l'App ID sont lus depuis les variables d'environnement (jamais en clair) :
    ONESIGNAL_API_KEY   clé REST API de l'app OneSignal (secret GitHub)
    ONESIGNAL_APP_ID    identifiant public de l'app OneSignal

Si la clé n'est pas définie, le script ne fait rien (sortie propre) : ainsi le
workflow ne casse pas tant que la notification n'est pas configurée.
"""

import json
import os
import sys
import urllib.request
import urllib.error

API_URL = "https://api.onesignal.com/notifications"

# Adresse de l'app : le clic sur la notification ouvre directement la revue.
APP_URL = "https://app.breve-app.fr"


def main() -> int:
    api_key = os.environ.get("ONESIGNAL_API_KEY", "").strip()
    app_id = os.environ.get("ONESIGNAL_APP_ID", "").strip()

    if not api_key or not app_id:
        print("OneSignal : clé ou App ID absents, notification ignorée.",
              file=sys.stderr)
        return 0  # on ne casse pas le workflow

    payload = {
        "app_id": app_id,
        "target_channel": "push",
        # Segment par défaut de CE compte OneSignal : « Total Subscriptions »
        # (badge Default), qui contient tous les abonnés. Le nom des segments
        # par défaut varie selon l'ancienneté du compte ; ici c'est celui-ci.
        "included_segments": ["Total Subscriptions"],
        # Pas de "headings" : le système (iOS/navigateur) affiche déjà « Brève »
        # comme expéditeur. Définir un titre « Brève » ferait doublon.
        "contents": {
            "en": "Votre revue du jour est prête",
            "fr": "Votre revue du jour est prête",
        },
        # Ouvre directement la revue au clic.
        "url": APP_URL,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    # Format d'autorisation actuel de OneSignal : "Key <clé>".
    req.add_header("Authorization", "Key " + api_key)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            info = json.loads(body) if body else {}
            # Un "id" renvoyé = notification créée. Pas d'id = aucun abonné
            # valide (ce n'est pas une erreur, juste personne à notifier).
            if info.get("id"):
                print(f"OneSignal : notification envoyée (id={info['id']}).",
                      file=sys.stderr)
            else:
                print(f"OneSignal : aucune notification créée "
                      f"(réponse : {body}).", file=sys.stderr)
            return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        print(f"OneSignal : erreur HTTP {e.code} : {detail}", file=sys.stderr)
        # On ne casse pas le workflow pour un souci de notification : la revue
        # elle-même a déjà été publiée, c'est l'essentiel.
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"OneSignal : erreur inattendue : {e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
