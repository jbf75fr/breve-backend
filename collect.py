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

    # tokens normalisés (titre + résumé) et termes saillants, calculés une fois
    _tokens: set[str] = field(default_factory=set, repr=False)
    _salient: set[str] = field(default_factory=set, repr=False)


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

def tokenize(text: str) -> set[str]:
    t = _strip_accents(text.lower())
    words = re.findall(r"[a-z0-9]+", t)
    return {w for w in words if len(w) > 2 and w not in _STOP}

# Mots très courants dans l'actualité : présents partout, peu distinctifs.
# On les ignore pour le repérage des "noms propres / termes saillants".
_COMMON = {
    "apres","avant","contre","face","cette","leur","leurs","mais","plus",
    "tout","tous","toute","fait","faire","etre","avoir","ans","pres","lors",
    "alors","selon","entre","depuis","jusqu","encore","aussi","ainsi","deux",
    "trois","premier","premiere","nouveau","nouvelle","grande","grand",
    "milliers","millions","journee","jour","matin","soir","semaine",
    "annonce","annoncee","direct","video","images","live","article",
}

def salient_tokens(title: str) -> set[str]:
    """
    Termes saillants d'un titre : noms propres et mots rares qui identifient
    le sujet (ex. « Colombie », « Espriella », « Ormuz », « Moscou »).
    On repère les mots commençant par une majuscule dans le titre original,
    plus les mots longs peu communs. C'est ce qui permet de reconnaître que
    deux titres très différents parlent du même événement.
    """
    sal = set()
    # mots capitalisés dans le titre d'origine (noms propres)
    for w in re.findall(r"\b[A-ZÀ-Ÿ][\wÀ-ÿ’'-]{2,}", title):
        norm = _strip_accents(w.lower())
        norm = re.sub(r"[^a-z0-9]", "", norm)
        if len(norm) > 2 and norm not in _STOP and norm not in _COMMON:
            sal.add(norm)
    # mots longs et distinctifs (chiffres-clés, termes rares)
    for w in tokenize(title):
        if len(w) >= 6 and w not in _COMMON:
            sal.add(w)
    return sal

def similar(a: Article, b: Article) -> float:
    """
    Similarité entre deux articles, combinant :
      - Jaccard sur les mots significatifs (titre + résumé),
      - bonus de recouvrement (part des mots du plus court présents dans l'autre),
      - ratio de séquence sur les titres (titres quasi identiques),
      - un FORT bonus si les articles partagent des termes saillants (noms
        propres) : c'est le signal décisif pour le même événement.
    """
    if not (a._tokens and b._tokens):
        return 0.0
    inter = len(a._tokens & b._tokens)
    union = len(a._tokens | b._tokens) or 1
    jaccard = inter / union
    overlap = inter / (min(len(a._tokens), len(b._tokens)) or 1)
    seq = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()

    base = 0.40 * jaccard + 0.35 * overlap + 0.10 * seq

    # bonus noms propres partagés
    shared_sal = a._salient & b._salient
    if len(shared_sal) >= 2:
        base += 0.45            # deux noms propres communs : très probablement le même sujet
    elif len(shared_sal) == 1:
        base += 0.18
    return min(base, 1.0)


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
        art._tokens = tokenize(title + " " + art.summary)
        art._salient = salient_tokens(title)
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


def _base_outlet(name: str) -> str:
    """
    Ramène « Le Monde Politique », « Le Monde Économie », « France Info Sport »…
    à leur média de base (« Le Monde », « France Info »). Sert à n'avoir qu'un
    seul angle par média réel dans une brève.
    """
    bases = ["Le Monde", "France Info", "France 24", "Libération",
             "Les Échos", "20 Minutes", "Courrier International",
             "Sciences et Avenir", "L'Équipe", "Numerama", "Reporterre"]
    for b in bases:
        if name.startswith(b):
            return b
    return name

def _dedup_articles(arts: list[Article]) -> list[Article]:
    """
    Au sein d'un dossier : retire les articles identiques (même lien) et ne
    garde qu'UN article par média de base (le plus riche en contenu). Évite
    les angles répétés et les « identique à la source précédente ».
    """
    by_link = {}
    for a in arts:
        # même lien = même article : on garde le plus informatif
        key = a.link
        if key not in by_link or len(a.summary) > len(by_link[key].summary):
            by_link[key] = a
    # puis un seul par média de base
    by_outlet = {}
    for a in by_link.values():
        b = _base_outlet(a.outlet)
        if b not in by_outlet or len(a.summary) > len(by_outlet[b].summary):
            by_outlet[b] = a
    # on renomme proprement chaque article avec son média de base
    out = []
    for a in by_outlet.values():
        a.outlet = _base_outlet(a.outlet)
        out.append(a)
    return out


def group_by_topic(articles: list[Article],
                   threshold: float = SIM_THRESHOLD) -> list[Dossier]:
    """
    Regroupe les articles par sujet via similarité (titre + résumé + noms
    propres). Un article rejoint un groupe si sa similarité avec le groupe
    dépasse le seuil. Chaque dossier est ensuite dédupliqué pour n'avoir
    qu'un seul angle par média réel.
    """
    dossiers: list[list[Article]] = []
    for art in articles:
        best_grp, best_score = None, 0.0
        for grp in dossiers:
            # on retient la MEILLEURE correspondance avec un membre du groupe :
            # deux articles du même sujet doivent se trouver même si le groupe
            # contient déjà d'autres articles moins proches.
            mx = max(similar(art, other) for other in grp)
            if mx > best_score:
                best_score, best_grp = mx, grp
        if best_grp is not None and best_score >= threshold:
            best_grp.append(art)
        else:
            dossiers.append([art])

    result = []
    for grp in dossiers:
        themes = [a.theme for a in grp if a.theme != "Général"]
        theme = max(set(themes), key=themes.count) if themes else grp[0].theme
        deduped = _dedup_articles(grp)
        result.append(Dossier(theme=theme, articles=deduped))
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
