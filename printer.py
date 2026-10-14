"""Impression SILENCIEUSE (jamais de boîte de dialogue) : PDF toujours archivé + impression directe si imprimante réelle.
Les imprimantes virtuelles (Microsoft Print to PDF, XPS, OneNote...) sont ignorées : ce sont elles qui ouvrent « Enregistrer sous »."""
import html, os
from datetime import datetime

from PyQt6.QtCore import QMarginsF, QSizeF, QUrl
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPageLayout, QPageSize, QPainter, QTextDocument
from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo

from branding import establishment, logo_path, print_resources
import templates
from config_manager import data_dir
from data_structures import SERVICE_BY_CODE
from database import FMT
from styles import TRIAGE_TEXT

VIRTUAL = ("pdf", "xps", "onenote", "fax", "writer", "snagit")
PX_PER_MM = 96 / 25.4          # QTextDocument raisonne en pixels logiques (96 dpi)


def _print(doc, pr):
    (getattr(doc, "print", None) or doc.print_)(pr)


def _print_overlay(doc, pr, tpl, margins):
    """Dessine la trame pré-imprimée (image/PDF) en fond de chaque page A4, puis le texte du document par-dessus."""
    t, l, r, b = [m * PX_PER_MM for m in margins]
    page_w, page_h = 210 * PX_PER_MM, 297 * PX_PER_MM
    cw, ch = page_w - l - r, page_h - t - b
    doc.setPageSize(QSizeF(cw, ch))
    painter = QPainter(pr)
    try:
        sc = pr.resolution() / 96.0
        painter.scale(sc, sc)
        for p in range(max(1, doc.pageCount())):
            if p:
                pr.newPage()
            painter.drawPixmap(QRectF(0, 0, page_w, page_h), tpl, QRectF(tpl.rect()))
            painter.save()
            painter.translate(l, t)
            painter.setClipRect(QRectF(0, 0, cw, ch))
            painter.translate(0, -p * ch)
            doc.drawContents(painter, QRectF(0, p * ch, cw, ch))
            painter.restore()
    finally:
        painter.end()


def is_virtual(name):
    return any(k in (name or "").lower() for k in VIRTUAL)


def physical_printers():
    return [n for n in QPrinterInfo.availablePrinterNames() if not is_virtual(n)]


def _make(pdf_path=None, name=None, size_mm=None, margin=2):
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    if pdf_path:
        pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        pr.setOutputFileName(pdf_path)
    elif name:
        pr.setPrinterName(name)
    page = QPageSize(QSizeF(*size_mm), QPageSize.Unit.Millimeter, "Doc") if size_mm else QPageSize(QPageSize.PageSizeId.A4)
    pr.setPageSize(page)
    pr.setPageMargins(QMarginsF(margin, margin, margin, margin), QPageLayout.Unit.Millimeter)
    return pr


def print_document(cfg, html_text, resources, kind, name, printer_name=None, width_mm=None, template_kind=None, tpl_pixmap=None):
    """kind = 'ticket' (rouleau 58/80 mm, hauteur ajustée au contenu) ou 'a4'.
    Retourne (ok, message). Le PDF est TOUJOURS enregistré dans %LOCALAPPDATA%\\Smart_DEM\\tickets|documents."""
    try:
        res = dict(print_resources())
        res.update(resources or {})
        doc = QTextDocument()
        for k, pix in res.items():
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(k), pix)
        doc.setHtml(html_text)
        tpl = None
        if kind == "ticket":
            margin, w = 2, float(width_mm or cfg.get("paper_width_mm", 80))
            doc.setTextWidth((w - 2 * margin) * PX_PER_MM)
            h_px = doc.size().height() + 4
            doc.setPageSize(QSizeF((w - 2 * margin) * PX_PER_MM, h_px))
            size_mm = (w, h_px / PX_PER_MM + 2 * margin + 2)
            folder, printer_cfg = "tickets", cfg.get("printer", "")
        else:
            tpl = tpl_pixmap if tpl_pixmap is not None else (templates.load_template(cfg, template_kind) if template_kind else None)   # trame importée (DB) ou locale
            margin, size_mm = (0 if tpl else 10), None
            doc.setPageSize(QSizeF((210 - 2 * margin) * PX_PER_MM, (297 - 2 * margin) * PX_PER_MM))
            folder, printer_cfg = os.path.join("documents", name.split("_")[0]), cfg.get("doc_printer", "")
        out = os.path.join(data_dir(), folder)
        os.makedirs(out, exist_ok=True)
        pdf = os.path.join(out, f"{name}_{datetime.now():%Y%m%d_%H%M%S}.pdf")
        out_fn = (lambda pr_: _print_overlay(doc, pr_, tpl, templates.margins_mm(cfg))) if (kind != "ticket" and tpl) else (lambda pr_: _print(doc, pr_))
        out_fn(_make(pdf_path=pdf, size_mm=size_mm, margin=margin))               # 1) archive PDF silencieuse
        target = printer_name if printer_name is not None else (printer_cfg or QPrinterInfo.defaultPrinterName())
        if target and not is_virtual(target) and target in QPrinterInfo.availablePrinterNames():
            out_fn(_make(name=target, size_mm=size_mm, margin=margin))           # 2) impression directe
            return True, f"Imprimé sur « {target} » — PDF : {pdf}"
        return True, f"PDF enregistré (aucune imprimante physique configurée) : {pdf}"
    except Exception as ex:   # l'impression ne doit jamais bloquer l'enregistrement
        return False, str(ex)


def ticket_html(cfg, row):
    svc = SERVICE_BY_CODE.get(row["service_code"], {"name": row["service_code"]})
    dt = datetime.strptime(row["created_at"], FMT)
    e = html.escape
    triage = TRIAGE_TEXT.get(row.get("triage_level") or "", "")
    triage_html = f"<p style='font-size:11pt;font-weight:bold;margin:2px'>{e(triage.upper())}</p>" if triage else ""
    name = f"{(row.get('last_name') or '').upper()} {row.get('first_name') or ''}".strip() or row.get("full_name", "")
    logo = "<img src='logo_ministere' width='34' height='34'>" if logo_path() else ""
    return f"""<div style='text-align:center;font-family:Arial'>
<table width='100%' cellspacing='0' cellpadding='0'><tr>
<td width='14%'>{logo}</td>
<td align='center'><p style='font-size:6pt;font-weight:bold;margin:0'>République Algérienne Démocratique et Populaire</p>
<p style='font-size:6pt;margin:0'>Ministère de la Santé</p></td>
<td width='14%' align='right'><img src='drapeau' width='34' height='34'></td></tr></table>
<p style='font-size:8pt;font-weight:bold;margin:2px 0 3px 0'>{e(establishment(cfg))}</p><hr>
<p style='font-size:11pt;margin:2px'>{e(svc['name'])}</p>
<p style='font-size:34pt;font-weight:bold;margin:2px'>{e(row['ticket_label'])}</p>{triage_html}
<p style='font-size:9pt;margin:2px'>{e(name)}</p>
<p style='font-size:8pt;margin:2px'>{dt:%d/%m/%Y  %H:%M}</p><hr>
<p style='font-size:8pt;margin:0'>Veuillez patienter. Merci.</p></div>"""


def print_ticket(cfg, row, printer_name=None, width_mm=None):
    return print_document(cfg, ticket_html(cfg, row), {}, "ticket", row["ticket_label"], printer_name, width_mm)


def appt_ticket_html(cfg, a):
    """Ticket de rendez-vous (rouleau 58/80 mm) : service, date, heure, n° de passage et QR code à scanner à l'arrivée (retourne (html, ressources))."""
    import html as _h
    from qr import qr_image
    from PyQt6.QtGui import QPixmap
    svc = SERVICE_BY_CODE.get(a.get("service_code") or "LAB", {"name": a.get("service_code") or "", "icon": ""})
    e = _h.escape
    res = {}
    img = qr_image(a["qr_text"], scale=6) if a.get("qr_text") else None
    qr_cell = ""
    if img is not None:
        res["qr"] = QPixmap.fromImage(img)
        qr_cell = "<p style='margin:3px'><img src='qr' width='120' height='120'></p>"
    logo = "<img src='logo_ministere' width='34' height='34'>" if logo_path() else ""
    d = datetime.strptime(a["date"], "%Y-%m-%d")
    html = f"""<div style='text-align:center;font-family:Arial'>
<table width='100%' cellspacing='0' cellpadding='0'><tr>
<td width='14%'>{logo}</td>
<td align='center'><p style='font-size:6pt;font-weight:bold;margin:0'>République Algérienne Démocratique et Populaire</p>
<p style='font-size:6pt;margin:0'>Ministère de la Santé</p></td>
<td width='14%' align='right'><img src='drapeau' width='34' height='34'></td></tr></table>
<p style='font-size:8pt;font-weight:bold;margin:2px 0 3px 0'>{e(establishment(cfg))}</p><hr>
<p style='font-size:10pt;font-weight:bold;margin:2px'>TICKET DE RENDEZ-VOUS</p>
<p style='font-size:11pt;margin:2px'>{e(svc['name'])}</p>
<p style='font-size:20pt;font-weight:bold;margin:2px'>{d:%d/%m/%Y} — {e(a['time'])}</p>
<p style='font-size:10pt;margin:2px'>N° de passage : <b>{e(str(a.get('number') or '-'))}</b></p>
<p style='font-size:9pt;margin:2px'>{e((a.get('last_name') or '').upper())} {e(a.get('first_name') or '')}</p>
{('<p style="font-size:8pt;margin:2px">' + e(a['exam']) + '</p>') if a.get('exam') else ''}{qr_cell}
<p style='font-size:7pt;margin:2px'>Présentez ce ticket (QR code) à l'accueil le jour du rendez-vous.</p><hr>
<p style='font-size:7pt;margin:0'>Merci d'être à l'heure.</p></div>"""
    return html, res


def print_appt_ticket(cfg, a, printer_name=None, width_mm=None):
    html, res = appt_ticket_html(cfg, a)
    return print_document(cfg, html, res, "ticket", f"RDV_{a['date']}_{a.get('number') or a['id']}", printer_name, width_mm)
