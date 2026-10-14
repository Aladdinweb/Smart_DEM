"""Modèles de documents / certificats médicaux par rôle (v1.4.0). Sans dépendance Qt : catalogue, extraction de texte, remplissage des champs.

Un modèle importé (txt, html, docx, png/jpg, pdf) est stocké sur le Hub : il est donc disponible sur tous les postes du même rôle.
  * texte / HTML / DOCX (texte seul) : champs {{nom}}, {{prenom}}, {{naissance}}, {{age}}, {{sexe}}, {{ident}}, {{date}}, {{medecin}}, {{fonction}}, {{service}}, {{etablissement}} remplacés à l'impression ;
  * image / PDF : trame pré-imprimée, le texte saisi est imprimé en surimpression ;
  * sans modèle importé : une mise en page standard (en-tête officiel + intitulé + champs + texte libre) est utilisée.
"""
import base64, html as _html, re, zipfile, io
from datetime import datetime

MAX_BYTES = 4 * 1024 * 1024
EXT_MIME = {".txt": "text/plain", ".html": "text/html", ".htm": "text/html", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}
FILE_FILTER = "Modèles (*.txt *.html *.htm *.docx *.png *.jpg *.jpeg *.pdf)"
PLACEHOLDERS = ("nom", "prenom", "naissance", "age", "sexe", "ident", "date", "medecin", "fonction", "service", "etablissement")

# clé -> (intitulé, rôle, fonctions concernées ou None = toutes les fonctions du rôle)
CATALOG = {
    "arret_travail":    ("Certificat d'arrêt de travail", "medecin", None),
    "bonne_sante":      ("Certificat de bonne santé", "medecin", None),
    "certificat_med":   ("Certificat médical (autre)", "medecin", None),
    "demande_bilan":    ("Demande de bilan / d'analyses", "medecin", None),
    "demande_ecg":      ("Demande d'ECG", "medecin", None),
    "ordonnance_type":  ("Ordonnance type", "medecin", None),
    "fiche_ophtalmo":   ("Fiche d'examen ophtalmologique", "medecin", {"OPTICIEN"}),
    "ordonnance_lunettes": ("Ordonnance de lunettes / verres", "medecin", {"OPTICIEN"}),
    "fiche_dentaire":   ("Fiche dentaire / schéma", "medecin", {"CHIRURGIEN-DENTISTE"}),
    "fiche_prelevement": ("Fiche de prélèvement", "labo", None),
    "formulaire_labo":  ("Formulaire d'examen spécifique (laboratoire)", "labo", None),
    "fiche_radio":      ("Fiche d'examen radiologique", "radio", None),
    "formulaire_radio": ("Formulaire spécifique (radiologie)", "radio", None),
}


def kinds_for(role, function=None):
    """[(clé, intitulé)] des modèles que ce rôle / cette fonction peut gérer et utiliser."""
    return [(k, t) for k, (t, r, fns) in CATALOG.items() if r == role and (fns is None or function in fns)]


def kind_title(kind):
    return CATALOG[kind][0] if kind in CATALOG else kind


def mime_of(filename):
    import os
    return EXT_MIME.get(os.path.splitext(filename or "")[1].lower())


def check_upload(filename, data):
    """ValueError si le fichier n'est pas un modèle acceptable. Retourne le type MIME."""
    mime = mime_of(filename)
    if not mime:
        raise ValueError("Format non pris en charge (txt, html, docx, png, jpg ou pdf).")
    if not data:
        raise ValueError("Fichier vide.")
    if len(data) > MAX_BYTES:
        raise ValueError("Fichier trop volumineux (4 Mo maximum).")
    if mime == "application/pdf" and not data.startswith(b"%PDF"):
        raise ValueError("Ce fichier n'est pas un PDF valide.")
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" and not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("Ce fichier n'est pas un document Word (.docx) valide.")
    return mime


def docx_text(data):
    """Texte brut d'un .docx (paragraphes ; la mise en forme Word n'est pas conservée)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        raise ValueError("Document Word illisible.")
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        p = re.sub(r"<w:tab\s*/>", "\t", p)
        p = re.sub(r"<w:br\s*/>", "\n", p)
        parts = re.findall(r"<w:t[^>]*>(.*?)</w:t>|(\t|\n)", p, flags=re.S)
        out.append(_html.unescape("".join(t or sep for t, sep in parts)))
    return "\n".join(out).strip()


def fill_fields(text, ctx):
    """Remplace {{champ}} (insensible à la casse / aux espaces) ; un champ inconnu est laissé vide."""
    return re.sub(r"\{\{\s*([A-Za-zÀ-ÿ_]+)\s*\}\}", lambda m: str(ctx.get(m.group(1).lower(), "")), text)


def patient_ctx(adm, user, cfg_establishment="", service=""):
    from database import age_from_row
    from functions import honorific
    adm = adm or {}
    return {"nom": (adm.get("last_name") or "").upper(), "prenom": adm.get("first_name") or "",
            "naissance": adm.get("birth_date") or (str(adm.get("birth_year")) if adm.get("birth_year") else ""),
            "age": f"{age_from_row(adm)} ans" if adm.get("birth_year") else "", "sexe": {"H": "Homme", "F": "Femme"}.get(adm.get("gender"), ""),
            "ident": adm.get("patient_ident") or "", "date": datetime.now().strftime("%d/%m/%Y"),
            "medecin": f"{honorific(user.get('function'))}{user.get('last_name', '')} {user.get('first_name', '')}".strip(),
            "fonction": user.get("function") or "", "service": service, "etablissement": cfg_establishment}


def decode(t):
    return base64.b64decode(t["content_b64"]) if t.get("content_b64") else b""


def body_html(t, ctx):
    """HTML du corps d'un modèle texte / HTML / DOCX rempli ; None si le modèle est une image / un PDF."""
    mime, data = t.get("mime") or "", decode(t)
    if mime == "text/html":
        return fill_fields(data.decode("utf-8", "replace"), {k: _html.escape(str(v)) for k, v in ctx.items()})
    if mime in ("text/plain", EXT_MIME[".docx"]):
        txt = data.decode("utf-8", "replace") if mime == "text/plain" else docx_text(data)
        txt = fill_fields(_html.escape(txt), {k: _html.escape(str(v)) for k, v in ctx.items()})
        return "<div style='font-size:12pt;line-height:140%'>" + txt.replace("\n", "<br>") + "</div>"
    return None


# Textes standard proposés tant qu'aucun modèle n'a été importé (à relire / adapter par le médecin avant impression)
DEFAULT_TEXT = {
    "arret_travail": "Je soussigné(e), {{medecin}}, certifie avoir examiné ce jour {{nom}} {{prenom}}, né(e) le {{naissance}}, dont l'état de santé nécessite un arrêt de travail de ....... jour(s), à compter du ....................\n\nSauf complication, reprise le ....................",
    "bonne_sante": "Je soussigné(e), {{medecin}}, certifie avoir examiné ce jour {{nom}} {{prenom}}, né(e) le {{naissance}}, et n'avoir constaté, à la date de l'examen, aucune affection apparente contre-indiquant ......................................\n\nCertificat établi à la demande de l'intéressé(e) pour servir et valoir ce que de droit.",
    "certificat_med": "Je soussigné(e), {{medecin}}, certifie avoir examiné ce jour {{nom}} {{prenom}}, né(e) le {{naissance}}.\n\n..............................................................................",
    "demande_bilan": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nBilan / analyses demandés :\n- \n- \n\nRenseignements cliniques : ....................",
    "demande_ecg": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nDemande d'électrocardiogramme (ECG) de repos.\n\nRenseignements cliniques : ....................",
    "ordonnance_type": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\n1. \n2. \n3. ",
    "fiche_ophtalmo": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nAcuité visuelle OD : ......  OG : ......\nTension oculaire OD : ......  OG : ......\nFond d'œil : ....................\nConclusion : ....................",
    "ordonnance_lunettes": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nOD : sph ...... cyl ...... axe ......  add ......\nOG : sph ...... cyl ...... axe ......  add ......\nÉcart pupillaire : ......",
    "fiche_dentaire": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nMotif : ....................\nDents concernées : ....................\nActe réalisé : ....................",
    "fiche_prelevement": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nPrélèvement : ....................   Heure : ........\nÀ jeun : oui / non\nTubes : ....................",
    "formulaire_labo": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nExamen : ....................\nRenseignements : ....................",
    "fiche_radio": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nExamen : ....................   Région : ....................\nIncidences : ....................\nObservations : ....................",
    "formulaire_radio": "Patient(e) : {{nom}} {{prenom}} — {{age}}\n\nExamen : ....................\nRenseignements : ....................",
}
