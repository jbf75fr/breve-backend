"""
collect.py : le cœur de Brève : collecte RSS + regroupement par sujet.

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
SIM_THRESHOLD = 0.42

# Seuil de la seconde passe : fusion de deux DOSSIERS entre eux. Volontairement
# plus haut que SIM_THRESHOLD : à ce stade on compare des sujets déjà constitués,
# et on ne veut fusionner que ce qui est manifestement le même fait.
MERGE_THRESHOLD = 0.50

# Un dossier partageant au moins ce nombre de médias avec un autre, ET des noms
# propres en commun, est très probablement le même sujet vu sous deux angles.
# Dans ce cas on abaisse l'exigence de similarité (voir _should_merge).
SHARED_OUTLETS_HINT = 2
MERGE_THRESHOLD_HINTED = 0.32
# Indice le plus fort (plusieurs médias ET plusieurs noms propres communs) :
# on peut descendre un peu plus bas encore.
MERGE_THRESHOLD_HINTED_STRONG = 0.28

# Nombre maximum de passes de fusion (sécurité : la boucle s'arrête d'elle-même
# dès qu'un tour ne fusionne plus rien).
MAX_MERGE_PASSES = 6

# Seuil relevé quand un dossier est un DÉVELOPPEMENT de l'autre (suite
# judiciaire, rebondissement) : il faut alors une ressemblance franche pour
# fusionner. Sert à garder « deux suspects avouent » séparé de l'incendie.
MERGE_THRESHOLD_DEV = 0.72


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
    # marqueurs de développement du titre, calculés à la demande puis mémorisés
    _dev: set[str] | None = field(default=None, repr=False)


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

# Élisions françaises collées au mot (l', d', qu'…). Sans ce nettoyage,
# « L'Assemblée » produisait le faux nom propre « lassemblee », distinct de
# « assemblee » : deux titres parlant de la même institution ne se
# reconnaissaient pas. Bug réel constaté sur la revue du 15 juillet 2026.
_ELISION = re.compile(r"^(l|d|j|n|s|c|t|m|qu|jusqu|lorsqu|puisqu)[’']", re.I)

def _norm_word(w: str) -> str:
    """Normalise un mot : retire l'élision initiale, les accents et la ponctuation."""
    w = _ELISION.sub("", w)
    w = _strip_accents(w.lower())
    return re.sub(r"[^a-z0-9]", "", w)

# Marqueurs de DÉVELOPPEMENT : vocabulaire propre aux suites judiciaires ou
# aux rebondissements d'une affaire. Quand un dossier en contient et pas
# l'autre, il s'agit de deux informations différentes sur un même sujet
# (« l'incendie a ravagé 2 000 hectares » et « deux suspects avouent »), qui
# méritent deux brèves. On refuse alors la fusion par indice de médias.
_DEVELOPPEMENT = {
    "garde", "vue", "suspects", "suspect", "interpelle", "interpelles",
    "arrete", "arretes", "avouent", "avoue", "enquete", "mis", "examen",
    "proces", "condamne", "condamnation", "plainte", "parquet", "juge",
    "inculpe", "perquisition", "detention", "auteur", "auteurs",
    "revendique", "demission", "demissionne", "limoge", "bilan", "victimes",
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
    # mots capitalisés dans le titre d'origine (noms propres), élision retirée
    for w in re.findall(r"\b[LDJNSCTM]['’][A-ZÀ-Ÿ][\wÀ-ÿ’'-]{2,}"
                        r"|\b[A-ZÀ-Ÿ][\wÀ-ÿ’'-]{2,}", title):
        norm = _norm_word(w)
        if len(norm) > 2 and norm not in _STOP and norm not in _COMMON:
            sal.add(norm)
    # mots longs et distinctifs (chiffres-clés, termes rares)
    for w in tokenize(title):
        if len(w) >= 6 and w not in _COMMON:
            sal.add(w)
    return sal

def _dev_focus(title: str) -> set[str]:
    """
    Marqueurs de développement présents dans le TITRE d'un article.

    Le titre dit ce dont l'article traite vraiment ; le corps, lui, mentionne
    souvent tout en passant (l'article sur l'incendie de Fontainebleau évoquait
    la garde à vue en une ligne, sans être l'article sur les suspects). Juger
    sur le corps produisait donc de faux positifs : on juge sur le titre.
    """
    return tokenize(title) & _DEVELOPPEMENT


def _dev_distinct(a: Article, b: Article) -> bool:
    """Vrai si l'un des deux titres annonce un développement et pas l'autre."""
    if a._dev is None:
        a._dev = _dev_focus(a.title)
    if b._dev is None:
        b._dev = _dev_focus(b.title)
    return bool(a._dev) != bool(b._dev)


def similar(a: Article, b: Article) -> float:
    """
    Similarité entre deux articles. Conçue pour être STRICTE : deux sujets ne
    fusionnent que s'ils partagent réellement plusieurs mots significatifs,
    pas un seul nom propre en commun (sinon « Colombie » dans deux sujets
    différents les collerait à tort).

    Combine :
      - Jaccard et recouvrement sur les mots significatifs (titre + résumé),
      - ratio de séquence sur les titres,
      - un bonus de noms propres communs qui n'est accordé QUE s'il y a déjà
        un recouvrement de base (le bonus renforce, il ne crée pas le lien).
    """
    if not (a._tokens and b._tokens):
        return 0.0
    inter = len(a._tokens & b._tokens)
    union = len(a._tokens | b._tokens) or 1
    jaccard = inter / union
    overlap = inter / (min(len(a._tokens), len(b._tokens)) or 1)
    seq = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()

    base = 0.50 * jaccard + 0.35 * overlap + 0.15 * seq

    # Garde-fou : il faut un minimum de mots communs pour envisager une fusion.
    # Un seul mot partagé ne suffit jamais.
    if inter < 2:
        return base * 0.5      # on étouffe le score : sujets trop peu liés

    # Bonus noms propres, accordé seulement si le recouvrement de base est déjà
    # réel (le bonus renforce un lien existant, il n'en invente pas).
    shared_sal = a._salient & b._salient
    if base >= 0.18:
        if len(shared_sal) >= 2:
            base += 0.30
        elif len(shared_sal) == 1:
            base += 0.10
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


def _link_articles(articles: list[Article],
                   threshold: float) -> list[list[Article]]:
    """
    Premier regroupement, par COMPOSANTES CONNEXES (fusion transitive).

    Différence essentielle avec l'ancienne méthode : si A ressemble à C et que
    B ressemble à C, alors A, B et C forment UN SEUL dossier, même si A et B ne
    se ressemblent pas directement. C'est le cas typique de trois angles d'un
    même événement (« La France éliminée », « L'Espagne qualifiée », « Coupe du
    monde : l'Espagne élimine la France ») : les deux premiers ne se croisent
    pas, le troisième fait le pont.

    Bénéfice secondaire : le résultat ne dépend plus de l'ordre d'arrivée des
    flux, qui est aléatoire (les flux répondent en parallèle).
    """
    n = len(articles)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    # Pré-filtre bon marché : deux articles sans AUCUN mot significatif commun
    # ne peuvent pas dépasser le seuil. Le test d'intersection d'ensembles est
    # très rapide, alors que similar() calcule un SequenceMatcher coûteux. Sur
    # une collecte réelle, l'immense majorité des paires est ainsi écartée.
    for i in range(n):
        a = articles[i]
        for j in range(i + 1, n):
            b = articles[j]
            if len(a._tokens & b._tokens) < 2:
                continue
            seuil = MERGE_THRESHOLD_DEV if _dev_distinct(a, b) else threshold
            if similar(a, b) >= seuil:
                union(i, j)

    groups: dict[int, list[Article]] = {}
    for i, art in enumerate(articles):
        groups.setdefault(find(i), []).append(art)
    # tri stable : le résultat ne doit pas dépendre de l'ordre des flux
    return sorted(groups.values(), key=_group_key)


def _group_signature(grp: list[Article]) -> tuple[set[str], set[str], set[str]]:
    """Vocabulaire, noms propres et médias d'un groupe d'articles."""
    tokens: set[str] = set()
    salient: set[str] = set()
    outlets: set[str] = set()
    for a in grp:
        tokens |= a._tokens
        salient |= a._salient
        outlets.add(_base_outlet(a.outlet))
    return tokens, salient, outlets


def _group_titles(grp: list[Article]) -> set[str]:
    """Vocabulaire des seuls TITRES d'un groupe."""
    out: set[str] = set()
    for a in grp:
        out |= tokenize(a.title)
    return out


def _group_similarity(g1: list[Article], g2: list[Article]) -> float:
    """
    Similarité entre deux GROUPES, calculée sur leur vocabulaire cumulé.
    Comparer les groupes entiers (et non deux articles isolés) rend le signal
    plus stable : un sujet couvert par cinq médias a un vocabulaire riche et
    bien identifié.
    """
    t1, s1, _ = _group_signature(g1)
    t2, s2, _ = _group_signature(g2)
    if not (t1 and t2):
        return 0.0
    inter = len(t1 & t2)
    union_n = len(t1 | t2) or 1
    jaccard = inter / union_n
    overlap = inter / (min(len(t1), len(t2)) or 1)

    # Composante TITRE, décisive. Le corps des articles dilue le signal : deux
    # brèves aux titres rigoureusement identiques (« L'Assemblée nationale vote
    # la loi sur l'aide à mourir », constaté deux fois le 15 juillet 2026) ne
    # se reconnaissaient pas, leurs corps étant rédigés différemment. Le titre
    # dit le sujet ; on lui donne donc son propre poids.
    n1, n2 = _group_titles(g1), _group_titles(g2)
    if n1 and n2:
        titre_ov = len(n1 & n2) / (min(len(n1), len(n2)) or 1)
    else:
        titre_ov = 0.0

    base = 0.30 * jaccard + 0.30 * overlap + 0.40 * titre_ov

    if inter < 3 and titre_ov < 0.6:
        return base * 0.5      # vocabulaire commun trop maigre

    shared_sal = s1 & s2
    if base >= 0.15:
        if len(shared_sal) >= 3:
            base += 0.30
        elif len(shared_sal) == 2:
            base += 0.18
        elif len(shared_sal) == 1:
            base += 0.06
    return min(base, 1.0)


def _should_merge(g1: list[Article], g2: list[Article]) -> bool:
    """
    Décide si deux dossiers doivent fusionner.

    Deux exigences, du plus strict au moins strict :
      1. similarité de vocabulaire au-dessus de MERGE_THRESHOLD ;
      2. OU, indice fort : les deux dossiers partagent plusieurs MÉDIAS et des
         noms propres. Qu'un même média (France 24, France Info) apparaisse
         dans deux dossiers proches signale presque toujours deux angles du même
         fait plutôt que deux sujets distincts. Dans ce cas seulement, on
         accepte un seuil de similarité plus bas.

    Volontairement prudent : un développement réellement nouveau (« deux
    suspects avouent » face à « l'incendie a ravagé 2 000 hectares ») possède
    son propre vocabulaire (garde à vue, suspects, enquête) et reste séparé.
    """
    t1, s1, o1 = _group_signature(g1)
    t2, s2, o2 = _group_signature(g2)

    # Garde-fou « développement » : si l'un des deux dossiers ANNONCE dans ses
    # titres une suite d'affaire (garde à vue, suspects, procès…) et pas
    # l'autre, ce sont deux informations distinctes sur un même sujet. On ne
    # fusionne alors que sur une similarité franche, jamais sur le simple
    # indice du partage de médias.
    dev1 = set().union(*(_dev_focus(a.title) for a in g1)) if g1 else set()
    dev2 = set().union(*(_dev_focus(a.title) for a in g2)) if g2 else set()
    developpement_distinct = bool(dev1) != bool(dev2)

    score = _group_similarity(g1, g2)
    if developpement_distinct:
        return score >= MERGE_THRESHOLD_DEV
    if score >= MERGE_THRESHOLD:
        return True

    shared_outlets = o1 & o2
    shared_salient = s1 & s2
    # Indice fort : plusieurs médias couvrent les deux dossiers ET il existe au
    # moins un nom propre commun. Exiger DEUX noms propres communs était trop
    # sévère : « Fin de vie : l'Assemblée vote mercredi » et « L'Assemblée
    # nationale vote la loi sur l'aide à mourir » ne partagent que
    # « Assemblée », alors qu'ils traitent du même vote (constaté le
    # 15 juillet 2026). Plus le partage de médias est large, plus l'indice est
    # fiable, donc plus le seuil de similarité peut être bas.
    if shared_outlets and shared_salient:
        seuil_indice = MERGE_THRESHOLD_HINTED
        if len(shared_outlets) >= SHARED_OUTLETS_HINT and len(shared_salient) >= 2:
            seuil_indice = MERGE_THRESHOLD_HINTED_STRONG
        elif len(shared_outlets) >= SHARED_OUTLETS_HINT:
            seuil_indice = MERGE_THRESHOLD_HINTED
        else:
            seuil_indice = MERGE_THRESHOLD          # un seul média : pas un indice
        if score >= seuil_indice:
            return True
    return False


def _group_key(grp: list[Article]) -> tuple:
    """
    Clé de tri STABLE d'un groupe, indépendante de l'ordre d'arrivée des flux.
    On trie sur des propriétés du contenu (taille, puis titres classés), jamais
    sur la position dans la liste.
    """
    titres = sorted(a.title for a in grp)
    return (-len(grp), titres[0] if titres else "")


def _merge_groups(groups: list[list[Article]]) -> list[list[Article]]:
    """
    Seconde passe : fusionne les dossiers entre eux, en boucle, jusqu'à ce
    qu'un tour complet ne fusionne plus rien (point fixe). Rattrape les cas où
    aucun article ne faisait individuellement le pont entre deux groupes.

    Deux précautions pour un résultat REPRODUCTIBLE (les flux RSS répondent en
    parallèle, donc dans un ordre imprévisible) :
      - les groupes sont triés par une clé de contenu avant chaque tour ;
      - à chaque tour on retient la MEILLEURE fusion possible, pas la première
        rencontrée. Sans cela, un article du Mondial changeait de dossier selon
        l'ordre de lecture des flux (constaté au test).
    """
    for _ in range(MAX_MERGE_PASSES):
        groups = sorted(groups, key=_group_key)
        merged_any = False
        out: list[list[Article]] = []
        for grp in groups:
            best, best_score = None, -1.0
            for cand in out:
                if _should_merge(cand, grp):
                    sc = _group_similarity(cand, grp)
                    if sc > best_score:
                        best, best_score = cand, sc
            if best is not None:
                best.extend(grp)
                merged_any = True
            else:
                out.append(list(grp))
        groups = out
        if not merged_any:
            break
    return sorted(groups, key=_group_key)


def group_by_topic(articles: list[Article],
                   threshold: float = SIM_THRESHOLD) -> list[Dossier]:
    """
    Regroupe les articles par sujet, en deux temps :

      1. `_link_articles` : composantes connexes sur la similarité article à
         article (fusion transitive, indépendante de l'ordre d'arrivée) ;
      2. `_merge_groups`  : fusion des dossiers qui restent trop proches, avec
         l'indice du partage de médias.

    Chaque dossier est ensuite dédupliqué pour n'avoir qu'un seul angle par
    média réel.
    """
    # Tri d'entrée STABLE : les flux RSS répondent en parallèle, donc dans un
    # ordre imprévisible. Sans ce tri, deux exécutions du même jour pouvaient
    # produire des regroupements différents (constaté au test).
    articles = sorted(articles, key=lambda a: (a.title, a.outlet, a.link))
    groups = _link_articles(articles, threshold)
    groups = _merge_groups(groups)

    result = []
    for grp in groups:
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
