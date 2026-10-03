"""Documents officiels A4 : ordonnance (griffe + QR), demande de radiologie, demande d'analyses."""
import base64, html
from datetime import datetime

from PyQt6.QtGui import QPixmap

from data_structures import SERVICE_BY_CODE
from database import FMT, age_from_row, display_name
from qr import qr_image


def esc(s):
    return html.escape(str(s if s is not None else ""))


def header_html(cfg):
    return f"""<table width='100%' cellspacing='0' cellpadding='2'><tr>
<td width='80' align='left'><img src='logo_ministere' width='70' height='70'></td>
<td align='center'><p style='margin:0;font-size:12pt;font-weight:bold'>République Algérienne Démocratique et Populaire</p>
<p style='margin:0;font-size:11pt'>Ministère de la Santé</p>
<p style='margin:3px 0 0 0;font-size:10pt'>{esc(cfg.get('parent'))}<br>{esc(cfg.get('structure'))}</p></td>
<td width='80' align='right'><img src='drapeau' width='70' height='70'></td></tr></table><hr>"""


def _doctor_name(doc):
    return f"Dr {doc['last_name']} {doc['first_name']}" + (f" — {doc['specialty']}" if doc.get("specialty") else "") if doc else ""


def _patient_line(adm):
    sex = "Homme" if adm["gender"] == "H" else "Femme"
    return f"<b>{esc(display_name(adm))}</b> — {age_from_row(adm)} ans — {sex}"


def _griffe(doc, resources):
    """Griffe / tampon du médecin (PNG transparent) -> ressource 'griffe'."""
    b64 = (doc or {}).get("signature_b64")
    if not b64:
        return "<p style='font-size:9pt'>&nbsp;</p>"
    pix = QPixmap()
    pix.loadFromData(base64.b64decode(b64))
    if pix.isNull():
        return ""
    resources["griffe"] = pix
    return "<img src='griffe' width='170'>"


def _stamp(dt=None):
    return (dt or datetime.now()).strftime("%d/%m/%Y %H:%M")


def build_prescription(cfg, rx, adm, doctor):
    res = {}
    rows = "".join(f"<tr><td align='center'>{i}</td><td><b>{esc(it['drug'])}</b></td><td>{esc(it['dosage'])}</td><td>{esc(it['duration'])}</td></tr>"
                   for i, it in enumerate(rx["items"], 1))
    img = qr_image(rx["qr_text"])
    if img:
        res["qr"] = QPixmap.fromImage(img)
        qr_cell = "<img src='qr' width='120' height='120'>"
    else:
        qr_cell = "<p style='font-size:8pt'>QR indisponible</p>"
    notes = f"<p><b>Remarques :</b> {esc(rx['notes'])}</p>" if rx.get("notes") else ""
    created = datetime.strptime(rx["created_at"], FMT)
    body = f"""{header_html(cfg)}
<h2 align='center' style='margin:4px'>ORDONNANCE MÉDICALE</h2>
<table width='100%'><tr><td>{esc(_doctor_name(doctor))}</td><td align='right'>Le {_stamp(created)}</td></tr></table>
<p>Patient : {_patient_line(adm)}</p>
<table width='100%' border='1' cellspacing='0' cellpadding='6'>
<tr style='background:#e8e8e8'><th width='6%'>N°</th><th>Médicament</th><th width='26%'>Posologie</th><th width='18%'>Durée</th></tr>{rows}</table>{notes}
<br><table width='100%'><tr>
<td width='50%' valign='top'><p style='font-size:9pt'>Cachet et signature du médecin</p>{_griffe(doctor, res)}</td>
<td width='50%' align='right' valign='top'>{qr_cell}<p style='font-size:8pt;margin:0'>Code : {esc(rx['uuid'][:8].upper())}<br>Vérifiable en pharmacie (QR Code)</p></td></tr></table>"""
    return body, res


def build_radio_request(cfg, req, adm, doctor):
    res = {}
    urgent = "<p style='color:#c00000;font-weight:bold'>URGENT</p>" if req.get("urgent") else ""
    body = f"""{header_html(cfg)}
<h2 align='center' style='margin:4px'>DEMANDE D'EXAMEN RADIOLOGIQUE</h2>{urgent}
<table width='100%'><tr><td>{esc(_doctor_name(doctor))}</td><td align='right'>Le {_stamp()} — N° de passage : <b>{esc(req['ticket_label'])}</b></td></tr></table>
<p>Patient : {_patient_line(adm)}</p>
<table width='100%' border='1' cellspacing='0' cellpadding='6'>
<tr><td width='30%'><b>Type d'examen</b></td><td>{esc(req['exam_type'])}</td></tr>
<tr><td><b>Région anatomique</b></td><td>{esc(req['region'])}</td></tr>
<tr><td><b>Côté</b></td><td>{esc(req['side'])}</td></tr>
<tr><td valign='top'><b>Renseignements cliniques</b></td><td>{esc(req.get('clinical_info')).replace(chr(10), '<br>')}</td></tr></table>
<br><p style='font-size:9pt'>Cachet et signature du médecin</p>{_griffe(doctor, res)}"""
    return body, res


def build_lab_request(cfg, lab, adm, doctor):
    res = {}
    items = "".join(f"<li>{esc(i)}</li>" for i in lab["items"])
    body = f"""{header_html(cfg)}
<h2 align='center' style='margin:4px'>DEMANDE D'ANALYSES BIOLOGIQUES</h2>
<table width='100%'><tr><td>{esc(_doctor_name(doctor))}</td><td align='right'>Le {_stamp()}</td></tr></table>
<p>Patient : {_patient_line(adm)}</p>
<p><b>Analyses demandées :</b></p><ul>{items}</ul>
<p><b>Renseignements cliniques :</b> {esc(lab.get('clinical_info')).replace(chr(10), '<br>')}</p>
<br><p style='font-size:9pt'>Cachet et signature du médecin</p>{_griffe(doctor, res)}"""
    return body, res
