"""
Flux RSS des médias français, organisés par thématique Brève.

Chaque entrée : (nom_du_média, url_du_flux, thème).
Le thème sert d'indice de départ ; le regroupement et l'IA peuvent
le raffiner ensuite. Plusieurs médias par thème = sources croisées.

Ces URL sont publiques et gratuites (pas de licence AFP payante).
Vérifiez-les périodiquement : les éditeurs changent parfois leurs flux.
"""

FEEDS = [
    # --- Généralistes / Une (alimentent plusieurs thèmes) ---
    ("France Info",          "https://www.franceinfo.fr/titres.rss",                          "Général"),
    ("Le Monde",             "https://www.lemonde.fr/rss/une.xml",                            "Général"),
    ("Libération",           "https://www.liberation.fr/arc/outboundfeeds/rss/?outputType=xml","Général"),
    ("France 24",            "https://www.france24.com/fr/france/rss",                        "Général"),
    ("20 Minutes",           "https://www.20minutes.fr/feeds/rss-une.xml",                    "Général"),
    ("Le Point",             "https://www.lepoint.fr/rss.xml",                                "Général"),

    # --- France (vie politique et nationale) ---
    ("France Info Politique","https://www.franceinfo.fr/politique.rss",                       "France"),
    ("Le Monde Politique",   "https://www.lemonde.fr/politique/rss_full.xml",                 "France"),
    ("Le Figaro Politique",  "https://www.lefigaro.fr/rss/figaro_politique.xml",              "France"),
    ("L'Humanité",           "https://www.humanite.fr/feed",                                  "France"),

    # --- Économie ---
    ("Le Monde Économie",    "https://www.lemonde.fr/economie/rss_full.xml",                  "Économie"),
    ("Les Échos",            "https://services.lesechos.fr/rss/les-echos-economie.xml",       "Économie"),
    ("France Info Éco",      "https://www.franceinfo.fr/economie.rss",                        "Économie"),
    ("Le Figaro Éco",        "https://www.lefigaro.fr/rss/figaro_economie.xml",               "Économie"),
    ("L'Opinion",            "https://www.lopinion.fr/feed",                                  "Économie"),

    # --- Monde (actualité internationale) ---
    ("Le Monde International","https://www.lemonde.fr/international/rss_full.xml",             "Monde"),
    ("France 24 Monde",      "https://www.france24.com/fr/rss",                               "Monde"),
    ("Courrier International","https://www.courrierinternational.com/feed/all/rss.xml",        "Monde"),
    ("Le Figaro International","https://www.lefigaro.fr/rss/figaro_international.xml",         "Monde"),

    # --- Tech & Sciences (fusionnées) ---
    ("Numerama",             "https://www.numerama.com/feed/",                                "Tech & Sciences"),
    ("Le Monde Pixels",      "https://www.lemonde.fr/pixels/rss_full.xml",                    "Tech & Sciences"),
    ("Sciences et Avenir",   "https://www.sciencesetavenir.fr/rss.xml",                       "Tech & Sciences"),
    ("Le Monde Sciences",    "https://www.lemonde.fr/sciences/rss_full.xml",                  "Tech & Sciences"),
    ("Le Figaro Sciences",   "https://www.lefigaro.fr/rss/figaro_sciences.xml",               "Tech & Sciences"),

    # --- Culture ---
    ("France Info Culture",  "https://www.franceinfo.fr/culture.rss",                         "Culture"),
    ("Le Monde Culture",     "https://www.lemonde.fr/culture/rss_full.xml",                   "Culture"),

    # --- Sport ---
    ("L'Équipe",             "https://www.lequipe.fr/rss/actu_rss.xml",                       "Sport"),
    ("France Info Sport",    "https://www.franceinfo.fr/sports.rss",                          "Sport"),

    # --- Environnement (élargi depuis Climat) ---
    ("Le Monde Planète",     "https://www.lemonde.fr/planete/rss_full.xml",                   "Environnement"),
    ("Reporterre",           "https://reporterre.net/spip.php?page=backend",                  "Environnement"),

    # --- Santé ---
    ("France Info Santé",    "https://www.franceinfo.fr/sante.rss",                           "Santé"),
    ("Le Monde Santé",       "https://www.lemonde.fr/sante/rss_full.xml",                     "Santé"),

    # --- Société (faits de société, éducation, justice) ---
    ("France Info Société",  "https://www.franceinfo.fr/societe.rss",                         "Société"),
    ("Le Monde Société",     "https://www.lemonde.fr/societe/rss_full.xml",                   "Société"),
    ("Mediapart",            "https://www.mediapart.fr/articles/feed",                        "Société"),
    ("Politis",              "https://www.politis.fr/flux-rss-apps/",                         "Société"),

    # --- Insolite ---
    # 20 Minutes Insolite est un flux dédié qui fonctionne. En complément,
    # l'IA (summarize.py) classe aussi en « Insolite » les sujets légers et
    # étonnants repérés dans les flux généralistes — ce qui aide au recoupement
    # (règle des 2 sources) et garantit du contenu même les jours creux.
    ("20 Minutes Insolite",  "https://www.20minutes.fr/feeds/rss-insolite.xml",               "Insolite"),
]

# Mapping des thèmes "Général" vers les thématiques Brève se fait à l'étape IA,
# qui classe chaque sujet. Les thèmes ci-dessous correspondent à ceux de l'app :
THEMES_BREVE = ["France", "Monde", "Économie", "Tech & Sciences", "Culture",
                "Sport", "Santé", "Environnement", "Société", "Insolite"]
