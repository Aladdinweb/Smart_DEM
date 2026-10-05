"""Documents officiels A4 : ordonnance (griffe + signature + QR + code-barres), demande de radiologie / d'analyses, résultat.
Si un modèle personnalisé (trame pré-imprimée) est configuré, l'en-tête est omis : le texte est imprimé en surimpression."""
import base64, html
from datetime import datetime

from PyQt6.QtGui import QPixmap

import templates
from barcode import barcode_image
from branding import establishment, logo_path
from database import FMT, age_from_row, display_name
from qr import qr_image


def esc(s):
    return html.escape(str(s if s is not None else ""))


def header_html(cfg, kind=None):
    if kind and templates.has_template(cfg, kind):
        return ""                                   # la trame fournie contient déjà l'en-tête
    logo = "<img src='logo_ministere' width='70' height='70'>" if logo_path() else ""
    return f"""<table width='100%' cellspacing='0' cellpadding='2'><tr>
<td width='80' align='left'>{logo}</td>
<td align='center'><p style='margin:0;font-size:12pt;font-weight:bold'>République Algérienne Démocratique et Populaire</p>
<p style='margin:0;font-size:11pt'>Ministère de la Santé</p>
<p style='margin:3px 0 0 0;font-size:10pt;font-weight:bold'>{esc(establishment(cfg))}</p></td>
<td width='80' align='right'><img src='drapeau' width='70' height='70'></td></tr></table><hr>"""


def _doctor_name(doc):
    return f"Dr {doc['last_name']} {doc['first_name']}" + (f" — {doc['specialty']}" if doc.get("specialty") else "") if doc else ""


def _patient_line(adm):
    sex = "Homme" if adm["gender"] == "H" else "Femme"
    ident = f" — N° {esc(adm['patient_ident'])}" if adm.get("patient_ident") else ""
    return f"<b>{esc(display_name(adm))}</b> — {age_from_row(adm)} ans — {sex}{ident}"


def _load_png(b64, res, name):
    if not b64:
        return ""
    pix = QPixmap()
    pix.loadFromData(base64.b64decode(b64))
    if pix.isNull():
        return ""
    res[name] = pix
    return f"<img src='{name}' height='70'>"


def _griffe_and_signature(doc, resources):
    """Griffe (cachet) et signature du médecin, imprimées côte à côte (PNG transparent : ancrage parfait sur toute trame)."""
    g = _load_png((doc or {}).get("signature_b64"), resources, "griffe")
    s = _load_png((doc or {}).get("sign_b64"), resources, "signature")
    return f"{g} &nbsp; {s}" if (g or s) else "<p style='font-size:9pt'>&nbsp;</p>"


def _stamp(dt=None):
    return (dt or datetime.now()).strftime("%d/%m/%Y %H:%M")


def build_prescription(cfg, rx, adm, doctor):
    res = {}
    rows = "".join(f"<tr><td align='center'>{i}</td><td><b>{esc(it['drug'])}</b></td><td>{esc(it['dosage'])}</td><td>{esc(it['duration'])}</td></tr>"
                   for i, it in enumerate(rx["items"], 1))
    img = qr_image(rx["qr_text"])
    qr_cell = "<p style='font-size:8pt'>QR indisponible</p>"
    if img:
        res["qr"] = QPixmap.fromImage(img)
        qr_cell = "<img src='qr' width='110' height='110'>"
    res["barcode"] = QPixmap.fromImage(barcode_image(rx["number"], module=2, height=48))
    notes = f"<p><b>Remarques :</b> {esc(rx['notes'])}</p>" if rx.get("notes") else ""
    created = datetime.strptime(rx["created_at"], FMT)
    body = f"""{header_html(cfg, 'ordonnance')}
<h2 align='center' style='margin:4px'>ORDONNANCE MÉDICALE</h2>
<table width='100%'><tr><td>{esc(_doctor_name(doctor))}</td><td align='right'>N° d'ordonnance : <b>{esc(rx['number'])}</b><br>Le {_stamp(created)}</td></tr></table>
<p>Patient : {_patient_line(adm)}</p>
<table width='100%' border='1' cellspacing='0' cellpadding='6'>
<tr style='background:#e8e8e8'><th width='6%'>N°</th><th>Médicament</th><th width='26%'>Posologie</th><th width='18%'>Durée</th></tr>{rows}</table>{notes}
<br><table width='100%'><tr>
<td width='50%' valign='top'><p style='font-size:9pt'>Cachet et signature du médecin</p>{_griffe_and_signature(doctor, res)}</td>
<td width='50%' align='right' valign='top'>{qr_cell}<br><img src='barcode' height='34'>
<p style='font-size:8pt;margin:0'>{esc(rx['number'])} — vérifiable en pharmacie</p></td></tr></table>"""
    return body, res


def build_radio_request(cfg, req, adm, doctor):
    res = {}
    urgent = "<p style='color:#c00000;font-weight:bold'>URGENT</p>" if req.get("urgent") else ""
    instr = f"<tr><td><b>Consignes spécifiques</b></td><td>{esc(req.get('instructions')).replace(chr(10), '<br>')}</td></tr>" if req.get("instructions") else ""
    body = f"""{header_html(cfg, 'imagerie')}
<h2 align='center' style='margin:4px'>DEMANDE D'EXAMEN RADIOLOGIQUE</h2>{urgent}
<table width='100%'><tr><td>{esc(_doctor_name(doctor))}</td><td align='right'>Le {_stamp()} — N° de passage : <b>{esc(req['ticket_label'])}</b></td></tr></table>
<p>Patient : {_patient_line(adm)}</p>
<table width='100%' border='1' cellspacing='0' cellpadding='6'>
<tr><td width='30%'><b>Type d'examen</b></td><td>{esc(req['exam_type'])}</td></tr>
<tr><td><b>Région anatomique</b></td><td>{esc(req['region'])}</td></tr>
<tr><td><b>Côté</b></td><td>{esc(req['side'])}</td></tr>
<tr><td valign='top'><b>Renseignements cliniques</b></td><td>{esc(req.get('clinical_info')).replace(chr(10), '<br>')}</td></tr>{instr}</table>
<br><p style='font-size:9pt'>Cachet et signature du médecin</p>{_griffe_and_signature(doctor, res)}"""
    return body, res


def build_lab_request(cfg, lab, adm, doctor):
    res = {}
    items = "".join(f"<li>{esc(i)}</li>" for i in lab["items"])
    urgent = "<p style='color:#c00000;font-weight:bold'>URGENT</p>" if lab.get("urgent") else ""
    body = f"""{header_html(cfg, 'bilan')}
<h2 align='center' style='margin:4px'>DEMANDE D'ANALYSES BIOLOGIQUES</h2>{urgent}
<table width='100%'><tr><td>{esc(_doctor_name(doctor))}</td><td align='right'>Le {_stamp()} — N° : <b>{esc(lab.get('ticket_label') or '')}</b></td></tr></table>
<p>Patient : {_patient_line(adm)}</p>
<p><b>Analyses demandées :</b></p><ul>{items}</ul>
<p><b>Renseignements cliniques :</b> {esc(lab.get('clinical_info')).replace(chr(10), '<br>')}</p>
<br><p style='font-size:9pt'>Cachet et signature du médecin</p>{_griffe_and_signature(doctor, res)}"""
    return body, res


def build_result(cfg, title, patient_line, ticket, exam_line, report_text, image_pix=None):
    """Cliché / compte rendu / résultat imprimé localement (remis au patient si nécessaire)."""
    res = {}
    img = ""
    if image_pix is not None:
        res["result_img"] = image_pix
        img = "<p align='center'><img src='result_img' width='640'></p>"
    body = f"""{header_html(cfg)}
<h2 align='center' style='margin:4px'>{esc(title)}</h2>
<p>Patient : {esc(patient_line)} — N° : <b>{esc(ticket)}</b> — {_stamp()}</p><p><b>{esc(exam_line)}</b></p>{img}
<p>{esc(report_text).replace(chr(10), '<br>')}</p>"""
    return body, res
