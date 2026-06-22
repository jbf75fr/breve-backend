"""
collect.py — Le cœur de Brève : collecte RSS + regroupement par sujet.

Étapes :
  1. Lit tous les flux RSS (feeds.py), en parallèle, avec tolérance aux pannes.
  2. Normalise chaque article (titre, lien, média, date, résumé, thème).
  3. Filtre sur une fenêtre temporelle (par défaut : dernières 24 h).
  4. Regroupe les articles qui parlent du MÊME sujet (dédup par similarité).
  5. Renvoie une liste de "dossiers", chacun = un sujet vu par 1..N sources.

Ce module ne fait PAS appel à l'IA : il prépare la matière première.
La génération des brèves (résumé + angles) est dans summarize.py.

Dépendances : feedparser  (pip install feedparser)
"""

from __future__ import annotations
import re
import unicodedata
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import feedparser

from feeds import FEEDS

# User-agent de navigateur : beaucoup d'éditeurs refusent les bots anonymes.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Fenêtre de fraîcheur : on ne garde que les articles récents.
FRESHNESS_HOURS = 24

# Seuil de similarité (0..1) au-delà duquel deux articles sont "le même sujet".
SIM_THRESHOLD = 0.34


# --------------------------------------------------------------------------- #
#  Modèle de données
# --------------------------------------------------------------------------- #
@dataclass
class Article:
    outlet: str
    theme: str
    title: str
    link: str
    summary: str
    published: dt.datetime | None

    # tokens normalisés du titre, calculés une fois (pour la similarité)
    _tokens: set[str] = field(default_factory=set, repr=False)


@dataclass
class Dossier:
    """Un sujet, potentiellement couvert par plusieurs médias."""
    theme: str
    articles: list[Article]

    @property
    def lead(self) -> Article:
        # l'article "principal" = le plus ancien connu (celui qui a lancé le sujet),
        # à défaut le premier.
        dated = [a for a in self.articles if a.published]
        return min(dated, key=lambda a: a.published) if dated else self.articles[0]

    @property
    def outlets(self) -> list[str]:
        seen, out = set(), []
        for a in self.articles:
            if a.outlet not in seen:
                seen.add(a.outlet); out.append(a.outlet)
        return out


# --------------------------------------------------------------------------- #
#  Normalisation de texte (pour comparer les titres)
# --------------------------------------------------------------------------- #
_STOP = {
    "le","la","les","un","une","des","de","du","au","aux","et","en","à","a",
    "pour","sur","dans","par","avec","sans","ce","ces","son","sa","ses","qui",
    "que","quoi","dont","est","sont","plus","moins","entre","vers","selon",
    "the","of","to","in","on","for","and","france","français","française"
}

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

def tokenize(title: str) -> set[str]:
    t = _strip_accents(title.lower())
    words = re.findall(r"[a-z0-9]+", t)
    return {w for w in words if len(w) > 2 and w not in _STOP}

def similar(a: Article, b: Article) -> float:
    """
    Similarité entre deux titres, combinant trois signaux :
      - Jaccard sur les mots significatifs (robuste aux reformulations),
      - ratio de séquence (capte les titres quasi identiques),
      - bonus de recouvrement : part des mots du titre le plus court qui
        se retrouvent dans l'autre (capte "même sujet, titre plus long").
    Le bonus de recouvrement permet de regrouper trois dépêches sur la
    canicule alors qu'elles n'emploient pas exactement les mêmes mots.
    """
    if not (a._tokens and b._tokens):
        return 0.0
    inter = len(a._tokens & b._tokens)
    union = len(a._tokens | b._tokens) or 1
    jaccard = inter / union
    overlap = inter / (min(len(a._tokens), len(b._tokens)) or 1)
    seq = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()
    return 0.45 * jaccard + 0.40 * overlap + 0.15 * seq


# --------------------------------------------------------------------------- #
#  Lecture d'un flux
# --------------------------------------------------------------------------- #
def _parse_date(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None)
        if val:
            try:
                return dt.datetime(*val[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
    return None

def _clean_html(raw: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def fetch_feed(name: str, url: str, theme: str) -> list[Article]:
    """Lit un flux et renvoie ses articles normalisés. Ne lève jamais : renvoie []."""
    try:
        d = feedparser.parse(url, agent=USER_AGENT)
    except Exception:
        return []
    out = []
    for e in d.entries:
        title = _clean_html(getattr(e, "title", "")).strip()
        link = getattr(e, "link", "").strip()
        if not title or not link:
            continue
        art = Article(
            outlet=name,
            theme=theme,
            title=title,
            link=link,
            summary=_clean_html(getattr(e, "summary", ""))[:600],
            published=_parse_date(e),
        )
        art._tokens = tokenize(title)
        out.append(art)
    return out


def fetch_all(feeds=FEEDS, max_workers: int = 12) -> list[Article]:
    """Lit tous les flux en parallèle."""
    articles: list[Article] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_feed, n, u, t): n for (n, u, t) in feeds}
        for fut in as_completed(futs):
            try:
                articles.extend(fut.result())
            except Exception:
                pass
    return articles


# --------------------------------------------------------------------------- #
#  Filtrage + regroupement
# --------------------------------------------------------------------------- #
def filter_fresh(articles: list[Article], hours: int = FRESHNESS_HOURS) -> list[Article]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    fresh = []
    for a in articles:
        # garde les articles récents OU sans date (prudence : on ne jette pas)
        if a.published is None or a.published >= cutoff:
            fresh.append(a)
    return fresh


def group_by_topic(articles: list[Article],
                   threshold: float = SIM_THRESHOLD) -> list[Dossier]:
    """
    Regroupe les articles par sujet via similarité de titres (clustering glouton).
    Un article rejoint un groupe si sa similarité MOYENNE avec les membres du
    groupe dépasse le seuil, OU s'il partage au moins deux mots distinctifs
    avec un membre (recouvrement fort). Comparer à la moyenne évite les
    "chaînes" trop laxistes tout en regroupant les reformulations d'un sujet.
    """
    dossiers: list[list[Article]] = []
    for art in articles:
        best_grp, best_score = None, 0.0
        for grp in dossiers:
            scores = [similar(art, other) for other in grp]
            avg = sum(scores) / len(scores)
            mx = max(scores)
            # un fort recouvrement ponctuel suffit (même sujet, titres variés)
            score = max(avg, mx * 0.85)
            if score > best_score:
                best_score, best_grp = score, grp
        if best_grp is not None and best_score >= threshold:
            best_grp.append(art)
        else:
            dossiers.append([art])

    result = []
    for grp in dossiers:
        themes = [a.theme for a in grp if a.theme != "Général"]
        theme = max(set(themes), key=themes.count) if themes else grp[0].theme
        result.append(Dossier(theme=theme, articles=grp))
    return result


def rank_dossiers(dossiers: list[Dossier]) -> list[Dossier]:
    """
    Classe les dossiers par importance : d'abord ceux couverts par le plus de
    médias distincts (signal d'importance), puis les plus récents.
    """
    def key(d: Dossier):
        n_outlets = len(d.outlets)
        recency = d.lead.published or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        return (n_outlets, recency)
    return sorted(dossiers, key=key, reverse=True)


# --------------------------------------------------------------------------- #
#  Pipeline complet
# --------------------------------------------------------------------------- #
def collect(min_outlets: int = 1, feeds=FEEDS) -> list[Dossier]:
    """
    Renvoie les dossiers du jour, classés par importance.
    min_outlets=2 imposerait le "minimum 2 sources" dès la collecte
    (à manier avec prudence : certains sujets frais n'ont qu'une source).
    feeds : liste de (nom, url, thème) ; par défaut la liste de feeds.py.
    """
    raw = fetch_all(feeds=feeds)
    fresh = filter_fresh(raw)
    dossiers = group_by_topic(fresh)
    dossiers = [d for d in dossiers if len(d.outlets) >= min_outlets]
    return rank_dossiers(dossiers)


if __name__ == "__main__":
    import sys
    print("Collecte en cours…", file=sys.stderr)
    dossiers = collect()
    print(f"\n{len(dossiers)} dossiers trouvés\n" + "=" * 60)
    for i, d in enumerate(dossiers[:20], 1):
        print(f"\n[{i}] {d.theme}  ·  {len(d.outlets)} source(s) : {', '.join(d.outlets)}")
        print(f"    {d.lead.title}")
        for a in d.articles:
            print(f"      - {a.outlet}: {a.link}")
