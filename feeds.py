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

    # --- Politique ---
    ("France Info Politique","https://www.franceinfo.fr/politique.rss",                       "Politique"),
    ("Le Monde Politique",   "https://www.lemonde.fr/politique/rss_full.xml",                 "Politique"),

    # --- Économie ---
    ("Le Monde Économie",    "https://www.lemonde.fr/economie/rss_full.xml",                  "Économie"),
    ("Les Échos",            "https://services.lesechos.fr/rss/les-echos-economie.xml",       "Économie"),
    ("France Info Éco",      "https://www.franceinfo.fr/economie.rss",                        "Économie"),

    # --- International ---
    ("Le Monde International","https://www.lemonde.fr/international/rss_full.xml",             "International"),
    ("France 24 Monde",      "https://www.france24.com/fr/rss",                               "International"),
    ("Courrier International","https://www.courrierinternational.com/feed/all/rss.xml",        "International"),

    # --- Technologie / Sciences ---
    ("Numerama",             "https://www.numerama.com/feed/",                                "Technologie"),
    ("Le Monde Pixels",      "https://www.lemonde.fr/pixels/rss_full.xml",                    "Technologie"),
    ("Sciences et Avenir",   "https://www.sciencesetavenir.fr/rss.xml",                       "Sciences"),
    ("Le Monde Sciences",    "https://www.lemonde.fr/sciences/rss_full.xml",                  "Sciences"),

    # --- Culture ---
    ("France Info Culture",  "https://www.franceinfo.fr/culture.rss",                         "Culture"),
    ("Le Monde Culture",     "https://www.lemonde.fr/culture/rss_full.xml",                   "Culture"),

    # --- Sport ---
    ("L'Équipe",             "https://www.lequipe.fr/rss/actu_rss.xml",                       "Sport"),
    ("France Info Sport",    "https://www.franceinfo.fr/sports.rss",                          "Sport"),

    # --- Climat / Environnement ---
    ("Le Monde Planète",     "https://www.lemonde.fr/planete/rss_full.xml",                   "Climat"),
    ("Reporterre",           "https://reporterre.net/spip.php?page=backend",                  "Climat"),

    # --- Santé ---
    ("France Info Santé",    "https://www.franceinfo.fr/sante.rss",                           "Santé"),
    ("Le Monde Santé",       "https://www.lemonde.fr/sante/rss_full.xml",                     "Santé"),

    # --- Insolite ---
    # 20 Minutes Insolite est un flux dédié qui fonctionne. En complément,
    # l'IA (summarize.py) classe aussi en « Insolite » les sujets légers et
    # étonnants repérés dans les flux généralistes — ce qui aide au recoupement
    # (règle des 2 sources) et garantit du contenu même les jours creux.
    ("20 Minutes Insolite",  "https://www.20minutes.fr/feeds/rss-insolite.xml",               "Insolite"),
]

# Mapping des thèmes "Général" vers les thématiques Brève se fait à l'étape IA,
# qui classe chaque sujet. Les thèmes ci-dessus correspondent à ceux de l'app :
THEMES_BREVE = ["Politique", "Économie", "International", "Technologie",
                "Sciences", "Culture", "Sport", "Climat", "Santé", "Insolite"]
