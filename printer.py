"""Impression directe du ticket (80 mm / 58 mm), sans boîte de dialogue."""
import html, os
from datetime import datetime

from PyQt6.QtCore import QMarginsF, QSizeF
from PyQt6.QtGui import QPageLayout, QPageSize, QTextDocument
from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo

from config_manager import data_dir
from data_structures import SERVICE_BY_CODE
from database import FMT
from styles import TRIAGE_TEXT


def ticket_html(cfg, row):
    svc = SERVICE_BY_CODE.get(row["service_code"], {"name": row["service_code"]})
    dt = datetime.strptime(row["created_at"], FMT)
    e = html.escape
    triage = TRIAGE_TEXT.get(row.get("triage_level") or "", "")
    triage_html = f"<p style='font-size:11pt;font-weight:bold;margin:2px'>{e(triage.upper())}</p>" if triage else ""
    return f"""<div style='text-align:center;font-family:Arial'>
<p style='font-size:10pt;font-weight:bold;margin:0'>{e(cfg.get('parent', ''))}</p>
<p style='font-size:9pt;margin:0 0 4px 0'>{e(cfg.get('structure', ''))}</p><hr>
<p style='font-size:11pt;margin:2px'>{e(svc['name'])}</p>
<p style='font-size:34pt;font-weight:bold;margin:2px'>{e(row['ticket_label'])}</p>{triage_html}
<p style='font-size:9pt;margin:2px'>{e(row['full_name'])}</p>
<p style='font-size:8pt;margin:2px'>{dt:%d/%m/%Y  %H:%M}</p><hr>
<p style='font-size:8pt;margin:0'>Veuillez patienter. Merci.</p></div>"""


def print_ticket(cfg, row, printer_name=None, width_mm=None):
    """Retourne (ok, message). Repli automatique en PDF si aucune imprimante n'est disponible."""
    name = cfg.get("printer", "") if printer_name is None else printer_name
    width = float(width_mm or cfg.get("paper_width_mm", 80))
    try:
        pr = QPrinter(QPrinter.PrinterMode.HighResolution)
        pdf_path = None
        if name == "__PDF__" or (not name and not QPrinterInfo.defaultPrinterName()):
            folder = os.path.join(data_dir(), "tickets")
            os.makedirs(folder, exist_ok=True)
            pdf_path = os.path.join(folder, f"{row['ticket_label']}_{datetime.now():%H%M%S}.pdf")
            pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            pr.setOutputFileName(pdf_path)
        elif name:
            pr.setPrinterName(name)
        pr.setPageSize(QPageSize(QSizeF(width, 160), QPageSize.Unit.Millimeter, "Ticket"))
        pr.setPageMargins(QMarginsF(2, 2, 2, 2), QPageLayout.Unit.Millimeter)
        doc = QTextDocument()
        doc.setHtml(ticket_html(cfg, row))
        doc.setPageSize(QSizeF(pr.pageRect(QPrinter.Unit.DevicePixel).size()))
        doc.print(pr)
        return True, (f"PDF : {pdf_path}" if pdf_path else "OK")
    except Exception as ex:  # l'impression ne doit jamais bloquer l'enregistrement
        return False, str(ex)
