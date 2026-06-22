# Faire tourner Brève automatiquement sur GitHub — sans terminal

Ce guide vous fait passer de « j'ai le code » à « la revue se génère toute
seule chaque matin », **entièrement depuis le navigateur**. Aucune commande à
taper. Comptez 20–30 minutes la première fois.

C'est **gratuit** : GitHub Actions offre largement assez de temps d'exécution
pour un script qui tourne une fois par jour.

---

## Vue d'ensemble (ce qu'on va faire)

1. Créer un compte GitHub.
2. Créer un « dépôt » (un espace pour votre code).
3. Y déposer les fichiers de Brève (glisser-déposer).
4. Ranger votre clé API dans le coffre-fort de GitHub.
5. Vérifier que ça marche en lançant le traitement à la main une fois.
6. C'est tout : ensuite il tourne seul chaque matin.

---

## Étape 1 — Créer un compte GitHub

Allez sur **github.com**, cliquez sur **Sign up**, suivez les instructions.
C'est gratuit. Notez bien votre identifiant et votre mot de passe.

---

## Étape 2 — Créer le dépôt

1. Une fois connecté, cliquez sur le **+** en haut à droite → **New repository**.
2. **Repository name** : tapez `breve` (ou ce que vous voulez).
3. Laissez-le **Private** (privé) si vous ne voulez pas que le code soit public.
4. Cochez **Add a README file**.
5. Cliquez **Create repository**.

Vous avez maintenant un espace vide prêt à recevoir les fichiers.

---

## Étape 3 — Déposer les fichiers de Brève

Le plus simple : le glisser-déposer.

1. Dans votre dépôt, cliquez sur **Add file** → **Upload files**.
2. Faites glisser **tous les fichiers** du dossier `breve-backend` :
   `feeds.py`, `collect.py`, `summarize.py`, `export.py`, `run_daily.py`,
   `requirements.txt`, et le dossier `public`.
3. **Important — le dossier caché `.github`** : le glisser-déposer ignore
   parfois les dossiers commençant par un point. Si c'est le cas, voir
   l'encadré ci-dessous pour créer le fichier de planification à la main.
4. En bas, cliquez **Commit changes**.

> ### Si le dossier `.github` n'est pas monté
> Créez le fichier directement sur GitHub :
> 1. **Add file** → **Create new file**.
> 2. Dans le nom, tapez exactement :
>    `.github/workflows/breve-daily.yml`
>    (les `/` créent automatiquement les dossiers).
> 3. Collez-y le contenu du fichier `breve-daily.yml` fourni.
> 4. **Commit changes**.

---

## Étape 4 — Ranger votre clé API en sécurité

Votre clé Anthropic ne doit JAMAIS être écrite dans le code. GitHub a un
coffre-fort prévu pour ça.

1. Dans votre dépôt, allez dans **Settings** (onglet en haut).
2. Menu de gauche : **Secrets and variables** → **Actions**.
3. Cliquez **New repository secret**.
4. **Name** : tapez exactement `ANTHROPIC_API_KEY`.
5. **Secret** : collez votre clé (obtenue sur console.anthropic.com).
6. **Add secret**.

La clé est maintenant chiffrée. Le workflow y accède sans jamais l'afficher.

---

## Étape 5 — Tester tout de suite (sans attendre demain matin)

1. Allez dans l'onglet **Actions** de votre dépôt.
2. Si GitHub demande d'activer les workflows, acceptez.
3. Dans la liste à gauche, cliquez sur **Brève — revue quotidienne**.
4. Bouton **Run workflow** (à droite) → confirmez **Run workflow**.
5. Au bout de quelques secondes, une exécution apparaît. Cliquez dessus pour
   suivre en direct. Chaque étape passe au vert si tout va bien.

Si tout est vert, un fichier `public/breves.json` apparaît dans votre dépôt :
**c'est votre revue, générée pour de vrai depuis les flux RSS et Claude.**

---

## Étape 6 — Laisser tourner

Il n'y a plus rien à faire. Le planning est déjà réglé : chaque matin vers
**5h30 (heure de Paris)**, GitHub relance le traitement et met à jour la revue.

Pour changer l'heure : modifiez la ligne `cron:` dans
`.github/workflows/breve-daily.yml` (directement sur GitHub, via le crayon
✏️ « Edit »). Le format est `minute heure * * *` en **heure UTC**
(Paris = UTC+2 en été, UTC+1 en hiver). Exemple : `30 3 * * *` = 5h30 Paris l'été.

---

## En cas de souci

- **Une étape est rouge dans Actions** : cliquez dessus, le message d'erreur
  explique. Le plus fréquent : la clé API manque ou est mal nommée (vérifiez
  qu'elle s'appelle exactement `ANTHROPIC_API_KEY`).
- **« Aucune brève générée »** : souvent les flux du moment n'avaient pas assez
  de sujets couverts par 2 sources. Vous pouvez abaisser l'exigence en changeant
  `--limit 12` en `--limit 12 --min-sources 1` dans le workflow.
- **Vérifier les flux sans IA** : lancez le workflow après avoir temporairement
  remplacé la commande par `python run_daily.py --dry-run`.

---

## Et la facture ?

- **GitHub Actions** : gratuit dans les limites mensuelles, très au-dessus
  d'un script quotidien. Vous ne paierez rien pour cet usage.
- **API Claude** : c'est le seul coût. Chaque exécution génère une douzaine de
  brèves avec un modèle économique (Haiku). Surveillez votre consommation sur
  la console Anthropic ; à ce rythme elle reste modeste.
