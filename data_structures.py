"""Wilayas, hiérarchie des établissements et catalogue des services."""
import json, os, re
from config_manager import data_dir

_NAMES = ("Adrar,Chlef,Laghouat,Oum El Bouaghi,Batna,Béjaïa,Biskra,Béchar,Blida,Bouira,Tamanrasset,Tébessa,"
          "Tlemcen,Tiaret,Tizi Ouzou,Alger,Djelfa,Jijel,Sétif,Saïda,Skikda,Sidi Bel Abbès,Annaba,Guelma,"
          "Constantine,Médéa,Mostaganem,M'Sila,Mascara,Ouargla,Oran,El Bayadh,Illizi,Bordj Bou Arréridj,"
          "Boumerdès,El Tarf,Tindouf,Tissemsilt,El Oued,Khenchela,Souk Ahras,Tipaza,Mila,Aïn Defla,Naâma,"
          "Aïn Témouchent,Ghardaïa,Relizane,Timimoun,Bordj Badji Mokhtar,Ouled Djellal,Béni Abbès,In Salah,"
          "In Guezzam,Touggourt,Djanet,El M'Ghair,El Meniaa").split(",")
WILAYAS = [f"{i:02d} - {n}" for i, n in enumerate(_NAMES, 1)]
TYPES = ["EPSP", "CHU", "EHU", "EPH"]

# {code_wilaya: {type: {établissement parent: [structures]}}}
# Complétez/étendez via structures.json (même format) placé dans le dossier de données.
DEFAULT_HIERARCHY = {
    "31": {
        "EPSP": {
            "EPSP ES SENIA": ["POLYCLINIQUE ES SENIA", "POLYCLINIQUE AADL AIN BEIDA",
                              "POLYCLINIQUE AIN BEIDA 1", "POLYCLINIQUE AIN BEIDA 2"],
            "EPSP MESSREGHIN": [], "EPSP SEDDIKIA": [], "EPSP AIN TURK": [], "EPSP FRONT DE MER": [],
        },
        "CHU": {}, "EHU": {}, "EPH": {},
    }
}


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def load_hierarchy():
    h = json.loads(json.dumps(DEFAULT_HIERARCHY))
    p = os.path.join(data_dir(), "structures.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                _merge(h, json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return h


HIERARCHY = load_hierarchy()


def wilaya_code(text):
    m = re.match(r"\s*(\d+)", text or "")
    return m.group(1).zfill(2) if m else ""


def parents(wilaya_text, type_):
    return list(HIERARCHY.get(wilaya_code(wilaya_text), {}).get(type_, {}).keys())


def structures(wilaya_text, type_, parent):
    return list(HIERARCHY.get(wilaya_code(wilaya_text), {}).get(type_, {}).get(parent, []))


CAT_GEN = "Consultations Générales & Urgences"
CAT_SPE = "Consultations Spécialisées"
CAT_EXA = "Examens & Soins"
CATEGORIES = [CAT_GEN, CAT_SPE, CAT_EXA]

SERVICES = [
    dict(code="URG", prefix="URG", icon="🚑", name="Urgences Médicales", cat=CAT_GEN, triage=True),
    dict(code="MG", prefix="MG", icon="🩺", name="Consultation Médecine Générale", cat=CAT_GEN, triage=True),
    dict(code="PED", prefix="PED", icon="👶", name="Pédiatrie", cat=CAT_GEN, triage=False),
    dict(code="DENT", prefix="DEN", icon="🦷", name="Chirurgie Dentaire", cat=CAT_GEN, triage=False),
    dict(code="DIAB", prefix="DIA", icon="🩸", name="Diabétologie & Endocrinologie", cat=CAT_SPE, triage=False),
    dict(code="NUT", prefix="NUT", icon="🥗", name="Nutrition", cat=CAT_SPE, triage=False),
    dict(code="OPT", prefix="OPT", icon="👓", name="Opticien / Optométrie", cat=CAT_SPE, triage=False),
    dict(code="SOINS", prefix="SOI", icon="💉", name="Salle de Soins", cat=CAT_EXA, triage=False),
    dict(code="LAB", prefix="LAB", icon="🧪", name="Laboratoire d'Analyses", cat=CAT_EXA, triage=False),
    dict(code="RAD", prefix="RAD", icon="🩻", name="Radiologie", cat=CAT_EXA, triage=False),
]
SERVICE_BY_CODE = {s["code"]: s for s in SERVICES}
