"""
summarize.py — Génère les brèves via l'API Anthropic (Claude).

Pour chaque dossier (un sujet + ses sources), on demande à Claude de produire,
dans le style éditorial de Brève :
  - title   : un titre clair et factuel
  - brief   : une phrase d'accroche (aperçu de la carte)
  - summary : le résumé (chapô du détail)
  - full    : le corps de la brève
  - theme   : la thématique Brève (parmi la liste fermée)
  - angles  : pour CHAQUE source, une phrase neutre décrivant son traitement

Principe de sobriété et de respect du droit d'auteur :
  - on ne reproduit pas les articles : on résume avec nos propres mots ;
  - on s'appuie sur le titre + le résumé RSS, et on lie toujours vers l'original ;
  - le ton est neutre, sans supposer l'intérêt ni l'opinion du lecteur.

Prérequis : une clé API dans la variable d'environnement ANTHROPIC_API_KEY.
    pip install anthropic
"""

from __future__ import annotations
import os
import json
import sys

from collect import Dossier
from feeds import THEMES_BREVE

# Modèle : Haiku est rapide et économique, adapté à un batch quotidien de
# dizaines de brèves. Passez à un modèle plus puissant si vous voulez une
# rédaction plus fine (au prix d'un coût plus élevé).
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1200

SYSTEM_PROMPT = f"""Tu es le rédacteur de « Brève », une revue de presse quotidienne française.
Ton rôle : à partir d'un sujet d'actualité et des articles de plusieurs médias,
rédiger UNE brève sobre, factuelle et neutre.

Règles impératives :
- Écris en français, vouvoiement, sans anglicismes inutiles.
- Reste strictement factuel. Ne suppose JAMAIS l'opinion, l'intérêt personnel
  ou la situation du lecteur. Pas de « pourquoi ça vous concerne ».
- Ne qualifie pas la ligne politique des médias.
- Reformule avec tes propres mots. Ne recopie pas les titres ou phrases des sources.
- Si les sources se contredisent, reste prudent et attribue.
- La thématique doit être choisie STRICTEMENT dans cette liste :
  {', '.join(THEMES_BREVE)}.

Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, de la forme :
{{
  "theme": "<une des thématiques autorisées>",
  "title": "<titre clair, ~10 mots>",
  "brief": "<une phrase d'accroche, ~15 mots>",
  "summary": "<résumé de 2 à 3 phrases>",
  "full": "<corps de la brève, 4 à 6 phrases>",
  "angles": [
    {{"outlet": "<nom du média>", "take": "<ce que cette source met en avant, 1 phrase neutre>"}}
  ]
}}
L'ordre et le nombre des angles doit correspondre aux sources fournies."""


def _client():
    """Crée le client Anthropic. Lève une erreur claire si la clé manque."""
    try:
        import anthropic
    except ImportError:
        raise SystemExit("Le paquet 'anthropic' n'est pas installé. Faites : pip install anthropic")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("Variable ANTHROPIC_API_KEY absente. Exportez votre clé API d'abord.")
    return anthropic.Anthropic(api_key=key)


def _dossier_to_prompt(d: Dossier) -> str:
    """Prépare la description d'un dossier envoyée à Claude."""
    lines = [f"Sujet pressenti (thème de départ : {d.theme}).", "", "Sources :"]
    for a in d.articles:
        lines.append(f"- Média : {a.outlet}")
        lines.append(f"  Titre : {a.title}")
        if a.summary:
            lines.append(f"  Extrait : {a.summary}")
        lines.append(f"  Lien : {a.link}")
    lines.append("")
    lines.append("Rédige la brève correspondante en respectant le format JSON demandé.")
    return "\n".join(lines)


def summarize_one(client, d: Dossier) -> dict | None:
    """Appelle Claude pour un dossier et renvoie la brève (dict) ou None si échec."""
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _dossier_to_prompt(d)}],
    )
    # Concatène les blocs texte de la réponse
    raw = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    raw = raw.strip()
    # Nettoie d'éventuelles balises de code
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # Réassocie les liens réels aux angles (par ordre, puis par nom de média)
    links_by_outlet = {a.outlet: a.link for a in d.articles}
    for ang in data.get("angles", []):
        ang["url"] = links_by_outlet.get(ang.get("outlet", ""), d.lead.link)

    # Garde-fou thème : on impose une valeur autorisée
    if data.get("theme") not in THEMES_BREVE:
        data["theme"] = d.theme if d.theme in THEMES_BREVE else THEMES_BREVE[0]
    return data


def build_breves(dossiers: list[Dossier], limit: int = 20,
                 min_sources: int = 2) -> list[dict]:
    """
    Génère les brèves pour les meilleurs dossiers.
    min_sources=2 applique la règle « au moins deux sources » de Brève
    (les dossiers à source unique sont ignorés ici).
    """
    client = _client()
    out = []
    eligible = [d for d in dossiers if len(d.outlets) >= min_sources]
    for i, d in enumerate(eligible[:limit]):
        try:
            data = summarize_one(client, d)
        except Exception as ex:
            print(f"  ! échec sur « {d.lead.title[:40]} » : {ex}", file=sys.stderr)
            continue
        if not data:
            print(f"  ! réponse non-JSON pour « {d.lead.title[:40]} »", file=sys.stderr)
            continue
        data["id"] = i
        data["priority"] = i + 1
        out.append(data)
        print(f"  ✓ {data['theme']:13} {data['title'][:50]}", file=sys.stderr)
    return out


if __name__ == "__main__":
    from collect import collect
    print("Collecte…", file=sys.stderr)
    dossiers = collect()
    print(f"{len(dossiers)} dossiers. Génération des brèves via Claude…", file=sys.stderr)
    breves = build_breves(dossiers)
    print(json.dumps(breves, ensure_ascii=False, indent=2))
