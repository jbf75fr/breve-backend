# Brève — le cœur (collecte RSS + génération IA)

Ce dossier contient le **backend** de Brève : le programme qui, chaque matin,
lit de vrais flux RSS de médias français, regroupe les articles par sujet,
puis demande à Claude de rédiger les brèves. Il produit un fichier de données
(`breves.json` / `breves.js`) que l'application affiche.

C'est la première brique d'une vraie application. Les autres (comptes,
notifications, apps mobiles) viendront ensuite et s'appuieront sur ce socle.

---

## Ce que fait ce backend

```
flux RSS  →  collecte  →  regroupement par sujet  →  Claude  →  breves.json
(feeds.py)  (collect.py)     (collect.py)        (summarize.py) (export.py)
```

- **`feeds.py`** — la liste des flux RSS français, par thème. Modifiable.
- **`collect.py`** — lit les flux, normalise, filtre sur 24 h, et **regroupe les
  articles qui parlent du même sujet** (déduplication, sources croisées).
- **`summarize.py`** — pour chaque sujet, appelle l'API Claude pour produire
  titre, accroche, résumé, corps et un angle par source. Renvoie du JSON.
- **`export.py`** — écrit `breves.json` et `breves.js`.
- **`run_daily.py`** — orchestre le tout : c'est le script du batch quotidien.

---

## Installation

```bash
cd breve-backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Test sans clé API (vérifier les flux)

```bash
python3 run_daily.py --dry-run
```
Affiche les sujets regroupés sans appeler l'IA. Sert à vérifier que les flux
RSS répondent et que le regroupement est correct.

## Exécution réelle

```bash
export ANTHROPIC_API_KEY="sk-ant-votre-cle"
python3 run_daily.py --limit 12 --out ./public
```
Génère `./public/breves.json` et `./public/breves.js`.

Obtenez une clé sur https://console.anthropic.com (compte développeur).

---

## Le rendez-vous quotidien (cron)

Pour générer la revue chaque matin à 5h30, ajoutez une tâche cron :

```cron
30 5 * * *  cd /chemin/breve-backend && /chemin/venv/bin/python run_daily.py --out /chemin/public >> /var/log/breve.log 2>&1
```

C'est le « batch matinal » : une seule exécution par jour, peu coûteuse,
qui prépare la revue avant le réveil des lecteurs.

---

## Points d'attention honnêtes

**1. Le regroupement par sujet n'est pas parfait.**
Il repose pour l'instant sur la similarité des titres. Ça marche bien quand les
médias emploient des mots proches, mais ça peut **rater des regroupements**
(deux titres très différents pour le même événement) ou, plus rarement, en
**fusionner à tort**. Le seuil se règle dans `collect.py` (`SIM_THRESHOLD`).
Pour une qualité nettement supérieure, l'étape suivante naturelle est d'utiliser
des *embeddings* (vecteurs de sens) plutôt que les seuls mots — c'est la
principale amélioration à prévoir.

**2. Coût de l'IA.**
Chaque brève = un appel à Claude. Un modèle économique (Haiku) suffit pour un
résumé factuel et limite la facture ; `summarize.py` l'utilise par défaut.
Le regroupement *avant* l'appel IA réduit le nombre d'appels (on ne résume pas
dix fois le même sujet). Surveillez votre consommation sur la console Anthropic.

**3. Droit d'auteur.**
Le système résume avec ses propres mots et lie toujours vers l'article original.
Il ne reproduit pas les textes des médias. Gardez ce principe : pas de copie,
toujours l'attribution et le lien. Les flux utilisés sont publics et gratuits
(pas de licence AFP payante).

**4. Robustesse des flux.**
Les éditeurs changent parfois l'URL de leurs flux, ou bloquent les robots. Le
code tolère les pannes (un flux en échec n'arrête pas les autres) mais vérifiez
périodiquement avec `--dry-run` que vos sources répondent toujours.

**5. Sujets transversaux.**
Un même événement peut relever de deux thèmes (ex. une canicule = Climat **et**
Santé). Le système attribue aujourd'hui un seul thème par brève. À affiner selon
votre choix éditorial.

---

## Et ensuite ?

Ce backend produit la revue. Les briques suivantes du projet :

- **Servir la revue** via une petite API (pour que les apps la récupèrent).
- **Comptes + connexion Google** (authentification, préférences par utilisateur).
- **Notifications quotidiennes** (quand la revue est prête).
- **Apps iPhone / Android** (bêta via TestFlight et Play Console).

Chacune demande des comptes et des services externes (hébergement, Apple,
Google). Le code peut être écrit ici ; leur mise en ligne se fait avec vos
identifiants.
