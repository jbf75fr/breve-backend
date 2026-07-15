"""
summarize.py : génère les brèves via l'API Anthropic (Claude).

Pour chaque dossier (un sujet + ses sources), on demande à Claude de produire,
dans le style éditorial de Brève :
  - themes  : 1 à 3 thématiques Brève (parmi la liste fermée)
  - title   : un titre clair et factuel
  - full    : le corps de la brève
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

# Filet de sécurité anti-doublon : deux brèves dont les titres se recouvrent
# à ce point (part des mots significatifs du plus court) sont considérées comme
# le même sujet, et la seconde est écartée. Seuil volontairement élevé : le
# regroupement de collect.py fait déjà le gros du travail, celui-ci ne rattrape
# que les cas flagrants sans écarter un développement légitime.
DOUBLON_TITRE_SEUIL = 0.75

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
- Sois CONCIS. Brève privilégie « moins mais mieux » : va à l'essentiel, chaque
  phrase doit apporter une information nouvelle. Ne délaye pas, ne répète pas.
- Le texte « full » commence par l'essentiel du fait, puis peut ajouter un
  complément utile (contexte, conséquence). N'allonge pas artificiellement :
  si le fait se dit en deux phrases, fais deux phrases.
- L'objectif d'une brève est de donner l'essentiel, PAS de remplacer l'article.
  Reste volontairement synthétique pour inviter le lecteur à consulter les
  sources d'origine s'il veut approfondir.
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
  "full": "<le corps de la brève : l'essentiel du fait, puis éventuellement un complément bref (contexte ou conséquence). 2 à 4 phrases, concis et sans redondance>",
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

    # On ne conserve QUE les champs attendus par l'app.
    full_text = _no_dash((data.get("full") or "").strip())
    return {
        "themes": data["themes"],
        "title": _no_dash((data.get("title") or "").strip()),
        "full": full_text,
        "angles": clean_angles,
    }


def _titre_tokens(titre: str) -> set[str]:
    """Mots significatifs d'un titre de brève, pour comparer deux brèves."""
    from collect import tokenize
    return tokenize(titre)


def _trop_proche(data: dict, deja: list[dict]) -> str | None:
    """
    Filet de sécurité APRÈS génération : renvoie le titre de la brève déjà
    retenue dont celle-ci est un doublon, ou None.

    Le regroupement de collect.py rattrape l'immense majorité des redondances,
    mais aucun regroupement n'est parfait. Cette vérification finale évite
    qu'une brève quasi identique à une autre n'arrive dans la revue. On compare
    les titres, qui disent le sujet, et on exige un recouvrement franc pour ne
    pas écarter un développement légitime.
    """
    t1 = _titre_tokens(data.get("title", ""))
    if not t1:
        return None
    for autre in deja:
        t2 = _titre_tokens(autre.get("title", ""))
        if not t2:
            continue
        recouvrement = len(t1 & t2) / (min(len(t1), len(t2)) or 1)
        if recouvrement >= DOUBLON_TITRE_SEUIL:
            return autre.get("title", "")
    return None


def build_breves(dossiers: list[Dossier], limit: int = 50,
                 min_sources: int = 2, per_theme: int = 5) -> list[dict]:
    """
    Génère les brèves pour les meilleurs dossiers.

    Deux garde-fous pour servir le lecteur sans surcharger :
      - min_sources : règle « au moins N sources » de Brève (def. 2) ;
      - per_theme   : nombre maximum de brèves par thème (def. 5). On vise
                      « jusqu'à » ce nombre : si l'actualité d'un thème est
                      pauvre un jour donné, on en aura moins, et c'est normal :
                      on ne fabrique pas d'actualité qui n'existe pas ;
      - limit       : plafond TOTAL de brèves, tous thèmes confondus (def. 50),
                      pour borner le coût et la durée du batch.

    Les dossiers sont déjà triés par importance par collect(). On les parcourt
    dans l'ordre et on s'arrête de générer pour un thème dès qu'il a atteint son
    quota, ce qui répartit naturellement les brèves entre thématiques.
    """
    client = _client()
    out = []
    per_theme_count: dict[str, int] = {}
    # Règle des sources : on exige « min_sources » médias pour tous les thèmes,
    # ce qui garantit pluralité et fiabilité. EXCEPTION pour « Insolite » : ces
    # sujets légers (record, anecdote, fait curieux) sont rarement repris par
    # plusieurs médias le même jour ; les écarter ferait disparaître le thème.
    # On les autorise donc avec une seule source. C'est sans risque de pluralité
    # politique (sujets non sensibles) et fidèle à l'esprit de Brève.
    eligible = [
        d for d in dossiers
        if len(d.outlets) >= min_sources or d.theme == "Insolite"
    ]

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
        # Filet de sécurité : écarte une brève quasi identique à une précédente.
        doublon = _trop_proche(data, out)
        if doublon:
            print(f"  ~ doublon écarté : « {data['title'][:40]} » "
                  f"(proche de « {doublon[:40]} »)", file=sys.stderr)
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
