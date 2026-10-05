"""Rapports statistiques anonymes pour la Direction de la Santé (DSP) : HTML (impression/PDF) et CSV. Aucune donnée nominative."""
import csv, html, io

from data_structures import SERVICE_BY_CODE


def _svc(code):
    return SERVICE_BY_CODE.get(code, {}).get("name", code)


def report_csv(st):
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Période", st["date_from"], st["date_to"]]); w.writerow([])
    w.writerow(["Indicateur", "Valeur"])
    for k, label in (("admissions", "Passages enregistrés"), ("avg_wait_min", "Attente moyenne avant appel (min)"), ("consultations", "Consultations clôturées"),
                     ("prescriptions", "Ordonnances"), ("lab_requests", "Demandes d'analyses"), ("radiology", "Examens de radiologie"),
                     ("appointments", "Rendez-vous de laboratoire")):
        w.writerow([label, st[k]])
    w.writerow([]); w.writerow(["Service", "Passages"])
    for code, n in st["by_service"].items():
        w.writerow([_svc(code), n])
    w.writerow([]); w.writerow(["Niveau de tri", "Passages"])
    for k, n in st["by_triage"].items():
        w.writerow([k, n])
    w.writerow([]); w.writerow(["Heure", "Passages"])
    for h, n in sorted(st["by_hour"].items()):
        w.writerow([f"{int(h):02d}h", n])
    return out.getvalue()


def report_html(cfg, st, header):
    e = html.escape
    def table(rows, head):
        return ("<table width='100%' border='1' cellspacing='0' cellpadding='4'><tr style='background:#e8e8e8'>"
                + "".join(f"<th align='left'>{e(h)}</th>" for h in head) + "</tr>"
                + "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</table>")
    ind = [("Passages enregistrés", st["admissions"]), ("Attente moyenne avant appel (min)", st["avg_wait_min"]),
           ("Consultations clôturées", st["consultations"]), ("Ordonnances", st["prescriptions"]),
           ("Demandes d'analyses", st["lab_requests"]), ("Examens de radiologie", st["radiology"]), ("Rendez-vous de laboratoire", st["appointments"])]
    return (f"{header}<h2 align='center'>RAPPORT STATISTIQUE — DIRECTION DE LA SANTÉ (DSP)</h2>"
            f"<p align='center'>Période du <b>{e(st['date_from'])}</b> au <b>{e(st['date_to'])}</b> — données agrégées, sans identité de patient</p>"
            f"<h3>Indicateurs</h3>{table(ind, ['Indicateur', 'Valeur'])}"
            f"<h3>Passages par service</h3>{table([(_svc(c), n) for c, n in st['by_service'].items()], ['Service', 'Passages'])}"
            f"<h3>Niveaux de tri médical</h3>{table(list(st['by_triage'].items()), ['Niveau', 'Passages'])}"
            f"<h3>Affluence par heure</h3>{table([(f'{int(h):02d}h', n) for h, n in sorted(st['by_hour'].items())], ['Heure', 'Passages'])}")
