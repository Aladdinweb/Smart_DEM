"""Fonctions officielles (liste FERMÉE) -> espace de travail (rôle technique). Pas de saisie libre d'une fonction."""
import unicodedata

# (libellé, rôle/espace, groupe d'affichage, services par défaut pour les médecins / spécialistes)
FUNCTIONS = [
    ("AGENT DE BUREAU", "accueil", "Accueil", ()), ("ADMINISTRATION", "accueil", "Accueil", ()), ("ASSISTANT SOCIAL", "accueil", "Accueil", ()),
    ("MÉDECIN", "medecin", "Consultation", ("MG",)), ("PÉDIATRE", "medecin", "Consultation", ("PED",)),
    ("PSYCHOLOGUE", "medecin", "Consultation", ("PSY",)), ("OPTICIEN", "medecin", "Consultation", ("OPT",)),
    ("CHIRURGIEN-DENTISTE", "medecin", "Consultation", ("DENT",)), ("RESPONSABLE URGENCES", "medecin", "Consultation", ("URG",)), ("COORDINATEUR DES MÉDECINS", "coord_med", "Consultation", ()),
    ("ISP", "soins", "Soins & Triage", ()), ("INFERMIER", "soins", "Soins & Triage", ()), ("SAGE FEMME", "soins", "Soins & Triage", ()),
    ("ATS", "soins", "Soins & Triage", ()), ("PARAMÉDICAL", "soins", "Soins & Triage", ()), ("ASSISTANTE MEDICAL", "soins", "Soins & Triage", ()),
    ("COORDINATEUR DE PARAMÉDICAL", "coord_para", "Soins & Triage", ()), ("SURVEILLANT", "coord_para", "Soins & Triage", ()),
    ("LABORANTIN", "labo", "Laboratoire", ()), ("PRÉLÈVEMENT", "labo", "Laboratoire", ()),
    ("MANIPULATEUR", "radio", "Radiologie", ()),
    ("PHARMACIEN", "pharmacie", "Pharmacie", ()),
]
LABELS = [f[0] for f in FUNCTIONS]
ROLE_OF = {f[0]: f[1] for f in FUNCTIONS}
DEFAULT_SERVICES = {f[0]: list(f[3]) for f in FUNCTIONS}
DOCTOR_TITLED = {"MÉDECIN", "PÉDIATRE", "CHIRURGIEN-DENTISTE", "RESPONSABLE URGENCES", "COORDINATEUR DES MÉDECINS"}      # titre « Dr »
ALERT_FUNCTIONS = {"RESPONSABLE URGENCES"}          # un médecin de cette fonction peut diffuser une alerte sur les écrans TV
SPACE_LABELS = {"accueil": "Accueil", "medecin": "Consultation", "radio": "Radiologie", "pharmacie": "Pharmacie", "labo": "Laboratoire",
                "soins": "Soins & Triage", "coord_med": "Coordination des médecins", "coord_para": "Coordination paramédicale"}
ROLES = tuple(SPACE_LABELS)

# Personnel paramédical AUTORISÉ à consulter l'historique clinique du dossier patient (v1.4.0). Les autres fonctions paramédicales
# (ATS, PARAMÉDICAL, ASSISTANTE MEDICAL) ne voient que l'identité et les passages. Les consultations de psychologie restent réservées aux médecins.
DPI_CLINICAL_PARAMED = {"ISP", "INFERMIER", "SAGE FEMME", "COORDINATEUR DE PARAMÉDICAL", "SURVEILLANT"}

# Groupes de coordination joignables par un agent (signalements) : clé -> (libellé, fonctions membres)
MSG_GROUPS = {
    "COORD_MED": ("Coordinateur des médecins", {"COORDINATEUR DES MÉDECINS"}),
    "COORD_PARA": ("Coordinateur paramédical", {"COORDINATEUR DE PARAMÉDICAL"}),
    "URGENCES": ("Responsable des urgences", {"RESPONSABLE URGENCES"}),
    "SURVEILLANT": ("Surveillant", {"SURVEILLANT"}),
}
# Fonctions habilitées à CONVOQUER / écrire à n'importe quel agent (les autres ne peuvent écrire qu'aux groupes ci-dessus et répondre)
MSG_COORDINATORS = set().union(*(g[1] for g in MSG_GROUPS.values()))


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).upper().replace("É", "E").split())


_BY_NORM = {norm(l): l for l in LABELS}


def match_function(text):
    """Libellé officiel si `text` correspond (sans tenir compte des accents / de la casse), sinon None."""
    return _BY_NORM.get(norm(text))


def default_function(role, services=()):
    services = list(services or [])
    if role == "medecin":
        return {"PED": "PÉDIATRE", "PSY": "PSYCHOLOGUE", "OPT": "OPTICIEN", "DENT": "CHIRURGIEN-DENTISTE"}.get(services[0], "MÉDECIN") if len(services) == 1 else "MÉDECIN"
    return {"accueil": "AGENT DE BUREAU", "radio": "MANIPULATEUR", "pharmacie": "PHARMACIEN", "labo": "LABORANTIN", "soins": "INFERMIER",
            "coord_med": "COORDINATEUR DES MÉDECINS", "coord_para": "COORDINATEUR DE PARAMÉDICAL"}[role]


def honorific(function):
    return "Dr " if function in DOCTOR_TITLED else ""


def format_vitals(v):
    """Résumé lisible des constantes vitales (aucune interprétation clinique)."""
    parts = []
    if v.get("sys"):
        parts.append(f"TA {v['sys']}/{v['dia']} {v.get('tension_unit', 'mmHg')}")
    if v.get("glyc"):
        parts.append(f"Glycémie {v['glyc']} {v.get('glyc_unit', 'g/L')}")
    if v.get("temp"):
        parts.append(f"T° {v['temp']} °C")
    if v.get("note"):
        parts.append(v["note"])
    return " · ".join(parts)
