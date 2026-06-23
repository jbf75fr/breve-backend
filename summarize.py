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
- N'utilise JAMAIS de tiret cadratin (—) ni de tiret demi-cadratin (–), ni
  dans les titres ni dans les textes. Pour une incise, utilise la virgule, les
  parenthèses ou le deux-points. Pour un intervalle, utilise « à » ou « et ».
  Le seul tiret autorisé est le trait d'union simple (-) des mots composés.
- Reste strictement factuel. Ne suppose JAMAIS l'opinion, l'intérêt personnel
  ou la situation du lecteur. Pas de « pourquoi ça vous concerne ».
- Ne qualifie pas la ligne politique des médias.
- Reformule avec tes propres mots. Ne recopie pas les titres ou phrases des sources.
- Si les sources se contredisent, reste prudent et attribue.
- Les thématiques doivent être choisies STRICTEMENT dans cette liste :
  {', '.join(THEMES_BREVE)}.
- Attribue 1 à 3 thématiques par brève, classées de la plus pertinente à la
  moins pertinente. Mets UN SEUL thème quand le sujet est net (la plupart des
  cas). N'ajoute un 2e (ou 3e) thème QUE si le sujet est réellement à cheval
  (ex. une cyberattaque d'hôpital = Tech & Sciences ET Santé ; une taxe carbone
  = Économie ET Environnement). Ne multiplie jamais les thèmes « pour ne rien
  rater » : un classement trop large perd tout son sens.
- Classe en « Insolite » les sujets légers, étonnants, cocasses ou décalés
  (record battu, histoire curieuse, fait divers amusant, anecdote surprenante).
  N'y mets jamais un sujet grave, dramatique ou sensible, même curieux : un
  drame reste dans sa thématique sérieuse (Monde, Société, France, etc.).

Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, et SANS
aucun champ supplémentaire que ceux demandés, de la forme :
{{
  "themes": ["<thématique principale>", "<thématique secondaire si pertinent>"],
  "title": "<titre clair, ~10 mots>",
  "brief": "<une phrase d'accroche, ~15 mots>",
  "summary": "<résumé de 2 à 3 phrases>",
  "full": "<corps de la brève, 4 à 6 phrases>",
  "angles": [
    {{"outlet": "<nom du média>", "take": "<ce que cette source met en avant, 1 phrase neutre>"}}
  ]
}}
Un SEUL angle par média (ne répète jamais deux fois le même média). Chaque
« take » doit être distinct et informatif ; n'écris jamais « identique à la
source précédente ». L'ordre des angles suit les sources fournies."""


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


def _no_dash(text: str) -> str:
    """
    Filet de sécurité : retire tout tiret cadratin (—) ou demi-cadratin (–) que
    l'IA aurait pu glisser malgré la consigne. On remplace par une ponctuation
    française correcte selon le contexte :
      - un tiret entouré d'espaces (incise) devient une virgule ;
      - un tiret entre deux nombres/mots (intervalle, ex. 2024–2025) devient
        un trait d'union simple.
    """
    if not text:
        return text
    import re
    t = text
    # Incise «  — » ou «  – » (espace avant/après) → virgule
    t = re.sub(r"\s*[—–]\s+", ", ", t)
    # Cas résiduel : tiret long collé (ex. intervalle 2024–2025) → trait d'union
    t = t.replace("—", "-").replace("–", "-")
    # Nettoyage d'éventuelles doubles virgules introduites
    t = re.sub(r",\s*,", ",", t)
    return t.strip()


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

    # Garde-fou thèmes : on accepte un tableau (nouveau format) ou un thème
    # unique (ancien format / tolérance), et on ne garde que des valeurs valides.
    raw_themes = data.get("themes")
    if not isinstance(raw_themes, list):
        # tolérance : ancien champ "theme" unique
        raw_themes = [data.get("theme")] if data.get("theme") else []
    themes = []
    for t in raw_themes:
        if isinstance(t, str) and t in THEMES_BREVE and t not in themes:
            themes.append(t)
    if not themes:
        # repli sur le thème pressenti du dossier
        themes = [d.theme if d.theme in THEMES_BREVE else THEMES_BREVE[0]]
    data["themes"] = themes

    # Réassocie les liens réels aux angles et déduplique par média.
    links_by_outlet = {a.outlet: a.link for a in d.articles}
    seen_outlets = set()
    clean_angles = []
    for ang in data.get("angles", []):
        outlet = (ang.get("outlet") or "").strip()
        if not outlet or outlet in seen_outlets:
            continue                       # évite les angles répétés du même média
        seen_outlets.add(outlet)
        clean_angles.append({
            "outlet": outlet,
            "take": _no_dash((ang.get("take") or "").strip()),
            "url": links_by_outlet.get(outlet, d.lead.link),
        })

    # On ne conserve QUE les champs attendus par l'app (supprime summary2 & co.)
    return {
        "themes": data["themes"],
        "title": _no_dash((data.get("title") or "").strip()),
        "brief": _no_dash((data.get("brief") or "").strip()),
        "summary": _no_dash((data.get("summary") or "").strip()),
        "full": _no_dash((data.get("full") or "").strip()),
        "angles": clean_angles,
    }


def build_breves(dossiers: list[Dossier], limit: int = 50,
                 min_sources: int = 2, per_theme: int = 5) -> list[dict]:
    """
    Génère les brèves pour les meilleurs dossiers.

    Deux garde-fous pour servir le lecteur sans surcharger :
      - min_sources : règle « au moins N sources » de Brève (def. 2) ;
      - per_theme   : nombre maximum de brèves par thème (def. 5). On vise
                      « jusqu'à » ce nombre : si l'actualité d'un thème est
                      pauvre un jour donné, on en aura moins, et c'est normal —
                      on ne fabrique pas d'actualité qui n'existe pas ;
      - limit       : plafond TOTAL de brèves, tous thèmes confondus (def. 50),
                      pour borner le coût et la durée du batch.

    Les dossiers sont déjà triés par importance par collect(). On les parcourt
    dans l'ordre et on s'arrête de générer pour un thème dès qu'il a atteint son
    quota — ce qui répartit naturellement les brèves entre thématiques.
    """
    client = _client()
    out = []
    per_theme_count: dict[str, int] = {}
    eligible = [d for d in dossiers if len(d.outlets) >= min_sources]

    for d in eligible:
        if len(out) >= limit:
            break  # plafond total atteint
        # Pré-filtre par le thème pressenti du dossier : si ce thème a déjà son
        # quota, inutile d'appeler l'IA (économie d'appels). Le thème final
        # confirmé par l'IA est revérifié juste après.
        tentative = d.theme if d.theme in THEMES_BREVE else None
        if tentative and per_theme_count.get(tentative, 0) >= per_theme:
            continue
        try:
            data = summarize_one(client, d)
        except Exception as ex:
            print(f"  ! échec sur « {d.lead.title[:40]} » : {ex}", file=sys.stderr)
            continue
        if not data:
            print(f"  ! réponse non-JSON pour « {d.lead.title[:40]} »", file=sys.stderr)
            continue
        # Quota appliqué sur le thème PRINCIPAL (1er tag) attribué par l'IA.
        theme = data["themes"][0]
        if per_theme_count.get(theme, 0) >= per_theme:
            continue
        per_theme_count[theme] = per_theme_count.get(theme, 0) + 1
        data["id"] = len(out)
        data["priority"] = len(out) + 1
        out.append(data)
        print(f"  ✓ {('/'.join(data['themes']))[:20]:20} {data['title'][:46]}", file=sys.stderr)
    return out


if __name__ == "__main__":
    from collect import collect
    print("Collecte…", file=sys.stderr)
    dossiers = collect()
    print(f"{len(dossiers)} dossiers. Génération des brèves via Claude…", file=sys.stderr)
    breves = build_breves(dossiers)
    print(json.dumps(breves, ensure_ascii=False, indent=2))
