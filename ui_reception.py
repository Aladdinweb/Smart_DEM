"""Bureau d'accueil & tri (rôles : Accueil Général et Poste Dédié)."""
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout)

from archive import archive_reception
from data_structures import CATEGORIES, SERVICES, SERVICE_BY_CODE
from database import FMT, birth_text, display_name, parse_age_or_birth
from printer import print_ticket
from styles import TRIAGE_COLORS, TRIAGE_ICON, TRIAGE_TEXT
from ui_common import BaseWindow, guard


class EditDialog(QDialog):
    """Correction d'une saisie erronée — le ticket garde son numéro."""
    def __init__(self, row, codes, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Modifier — {row['ticket_label']}")
        f = QFormLayout(self)
        self.last = QLineEdit(row.get("last_name") or row["full_name"]); self.first = QLineEdit(row.get("first_name") or "")
        self.age = QLineEdit(birth_text(row))
        self.gender = QComboBox(); self.gender.addItem("Homme", "H"); self.gender.addItem("Femme", "F")
        self.gender.setCurrentIndex(0 if row["gender"] == "H" else 1)
        self.service = QComboBox()
        for c in codes:
            s = SERVICE_BY_CODE[c]; self.service.addItem(f"{s['icon']} {s['name']}", c)
        self.service.setCurrentIndex(max(0, self.service.findData(row["service_code"])))
        self.triage = QComboBox()
        for k in ("VERT", "ORANGE", "ROUGE"):
            self.triage.addItem(f"{TRIAGE_ICON[k]} {TRIAGE_TEXT[k]}", k)
        self.triage.setCurrentIndex(max(0, self.triage.findData(row["triage_level"] or "VERT")))
        self.service.currentIndexChanged.connect(self._sync)
        f.addRow("Nom :", self.last); f.addRow("Prénom :", self.first); f.addRow("Âge / Date de naissance :", self.age)
        f.addRow("Genre :", self.gender); f.addRow("Service :", self.service); f.addRow("Niveau de tri :", self.triage)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); f.addRow(bb)
        self._sync()

    def _sync(self):
        self.triage.setEnabled(SERVICE_BY_CODE[self.service.currentData()]["triage"])

    def _ok(self):
        if len(self.last.text().strip()) < 2 or not self.first.text().strip() or not parse_age_or_birth(self.age.text()):
            QMessageBox.warning(self, "Modifier", "Nom, prénom ou âge / date de naissance invalide."); return
        self.accept()

    def values(self):
        return {"last_name": self.last.text(), "first_name": self.first.text(), "parsed": parse_age_or_birth(self.age.text()),
                "gender": self.gender.currentData(), "service_code": self.service.currentData(), "triage": self.triage.currentData()}


class ReceptionWindow(BaseWindow):
    USER_ROLES = ("accueil", "radio")

    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        if cfg.get("role") == "accueil":
            self.codes = [s["code"] for s in SERVICES]
        else:
            self.codes = [c for c in cfg.get("services", []) if c in SERVICE_BY_CODE]
        b = QPushButton("🔄 Réinitialiser les compteurs"); b.clicked.connect(self.reset_counters)
        self.header_extra.addWidget(b)
        body = QHBoxLayout(); self.content.addLayout(body, 1)
        body.addWidget(self._build_form(), 5)
        body.addWidget(self._build_history(), 6)
        self.stats = QLabel(); self.stats.setStyleSheet("font-size:15px;padding:6px 10px;")
        sf = QFrame(); sf.setObjectName("card"); QHBoxLayout(sf).addWidget(self.stats)
        self.content.addWidget(sf)
        self.reset_form()

    def hours(self):
        return int(self.cfg.get("revisit_check_hours", 72))

    def on_login(self):
        self.reset_form(); self.refresh()

    # ---------------- formulaire ----------------
    def _build_form(self):
        card = QFrame(); card.setObjectName("card")
        v = QVBoxLayout(card)
        t = QLabel("Enregistrement rapide"); t.setStyleSheet("font-size:18px;font-weight:700;"); v.addWidget(t)
        names = QHBoxLayout()
        self.last_edit = QLineEdit(); self.last_edit.setPlaceholderText("Nom (nom de famille)")
        self.first_edit = QLineEdit(); self.first_edit.setPlaceholderText("Prénom")
        names.addWidget(self.last_edit); names.addWidget(self.first_edit); v.addLayout(names)
        self.age_edit = QLineEdit(); self.age_edit.setPlaceholderText("Âge (ex : 35) ou date de naissance (jj/mm/aaaa)")
        v.addWidget(self.age_edit)
        gl = QHBoxLayout()
        self.gender_group = QButtonGroup(self)
        self.btn_h, self.btn_f = QPushButton("&Homme"), QPushButton("&Femme")
        for gbtn, code in ((self.btn_h, "H"), (self.btn_f, "F")):
            gbtn.setCheckable(True); gbtn.setProperty("code", code)
            self.gender_group.addButton(gbtn); gl.addWidget(gbtn)
        v.addLayout(gl)

        self.service_group = QButtonGroup(self)
        for cat in CATEGORIES:
            items = [s for s in SERVICES if s["cat"] == cat and s["code"] in self.codes]
            if not items:
                continue
            box = QGroupBox(cat); grid = QGridLayout(box)
            for i, s in enumerate(items):
                sb = QPushButton(f"{s['icon']}  {s['name']}")
                sb.setCheckable(True); sb.setProperty("service", True); sb.setProperty("code", s["code"])
                self.service_group.addButton(sb); grid.addWidget(sb, i // 2, i % 2)
            v.addWidget(box)
        self.service_group.buttonClicked.connect(lambda *_: self.on_service_changed())

        self.triage_box = QGroupBox("Niveau de tri médical"); tl = QHBoxLayout(self.triage_box)
        self.triage_group = QButtonGroup(self)
        for k in ("VERT", "ORANGE", "ROUGE"):
            tb = QPushButton(f"{TRIAGE_ICON[k]}  {TRIAGE_TEXT[k]}")
            tb.setCheckable(True); tb.setProperty("code", k)
            tb.setStyleSheet(f"QPushButton:checked{{background:{TRIAGE_COLORS[k]};color:white;border:none;}}")
            self.triage_group.addButton(tb); tl.addWidget(tb)
        v.addWidget(self.triage_box)
        v.addStretch()
        save = QPushButton("🖨  Enregistrer && Imprimer le Ticket   (Entrée)"); save.setObjectName("primary")
        save.clicked.connect(self.submit); v.addWidget(save)

        for w in (self.last_edit, self.first_edit, self.age_edit):
            w.returnPressed.connect(self.submit)
        self.age_edit.editingFinished.connect(self.check_live)
        self.first_edit.editingFinished.connect(self.check_live)
        self.gender_group.buttonClicked.connect(lambda *_: self.check_live())
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(card); sc.setMinimumWidth(560)
        return sc

    @staticmethod
    def _uncheck(group):
        b = group.checkedButton()
        if b:
            group.setExclusive(False); b.setChecked(False); group.setExclusive(True)

    def current_service(self):
        b = self.service_group.checkedButton()
        return SERVICE_BY_CODE[b.property("code")] if b else None

    def on_service_changed(self):
        s = self.current_service()
        self.triage_box.setVisible(bool(s and s["triage"]))
        self.check_live()

    def reset_form(self):
        self.last_edit.clear(); self.first_edit.clear(); self.age_edit.clear()
        self._uncheck(self.gender_group)
        if len(self.service_group.buttons()) == 1:
            self.service_group.buttons()[0].setChecked(True)
        else:
            self._uncheck(self.service_group)
        for b in self.triage_group.buttons():
            b.setChecked(b.property("code") == "VERT")
        self.on_service_changed()
        self.last_edit.setFocus()

    def _read_form(self):
        gb = self.gender_group.checkedButton()
        return (self.last_edit.text().strip(), self.first_edit.text().strip(), parse_age_or_birth(self.age_edit.text()),
                gb.property("code") if gb else None, self.current_service())

    @guard
    def check_live(self, *_):
        last, first, parsed, gender, _svc = self._read_form()
        if len(last) < 2 or not first or not parsed or not gender:
            return
        rev = self.db.find_revisit(last, first, gender, parsed, self.hours())
        self.show_revisit(rev) if rev else self.clear_revisit_banner()

    @guard
    def submit(self, *_):
        if not self.user:
            return
        last, first, parsed, gender, svc = self._read_form()
        if len(last) < 2: return self.show_banner("Saisissez le nom du patient.", "error")
        if not first: return self.show_banner("Saisissez le prénom du patient.", "error")
        if not parsed: return self.show_banner("Âge ou date de naissance invalide (ex : 35 ou 12/05/1989).", "error")
        if not gender: return self.show_banner("Sélectionnez le genre (Homme / Femme).", "error")
        if not svc: return self.show_banner("Sélectionnez un service.", "error")
        triage = self.triage_group.checkedButton().property("code") if svc["triage"] else None
        # Alerte purement informative : n'empêche JAMAIS l'enregistrement.
        rev = self.db.find_revisit(last, first, gender, parsed, self.hours())
        row = self.db.add_admission({"last_name": last, "first_name": first, "parsed": parsed, "gender": gender,
                                     "service_code": svc["code"], "triage": triage, "user_id": self.user["id"]}, self.station)
        ok, msg = print_ticket(self.cfg, row)          # impression silencieuse + PDF automatique
        try:
            archive_reception(row)                      # archivage automatique du dossier d'accueil
        except OSError as e:
            ok, msg = False, f"archivage impossible : {e}"
        self.reset_form(); self.refresh()
        if rev:
            self.show_revisit(rev)
        elif not ok:
            self.show_banner(f"Patient enregistré ({row['ticket_label']}) mais : {msg}", "error")
        else:
            self.hide_banner()

    # ---------------- historique ----------------
    def _build_history(self):
        card = QFrame(); card.setObjectName("card"); v = QVBoxLayout(card)
        top = QHBoxLayout()
        t = QLabel("Historique des admissions"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.search = QLineEdit(); self.search.setPlaceholderText("Rechercher nom / ticket…")
        self.only_shift = QCheckBox("Garde actuelle"); self.only_shift.setChecked(True)
        top.addWidget(t, 1); top.addWidget(self.search, 1); top.addWidget(self.only_shift)
        v.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Ticket", "Heure", "Date", "Nom & Prénom", "Service", "Niveau"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide(); self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        for i in range(6):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == 3 else QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table, 1)
        bl = QHBoxLayout()
        be = QPushButton("✏️ Modifier la sélection"); br = QPushButton("🖨 Réimprimer")
        be.clicked.connect(self.edit_selected); br.clicked.connect(self.reprint_selected)
        bl.addWidget(be); bl.addWidget(br); bl.addStretch(); v.addLayout(bl)
        self.table.doubleClicked.connect(lambda *_: self.edit_selected())
        self.search.textChanged.connect(self.refresh_history)
        self.only_shift.toggled.connect(self.refresh_history)
        return card

    def selected_id(self):
        it = self.table.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    @guard
    def refresh_history(self, *_):
        if not self.user:
            return
        sel = self.selected_id()
        sid = self.db.current_shift(self.station) if self.only_shift.isChecked() else None
        rows = self.db.history(sid, self.search.text().strip())
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            dt = datetime.strptime(r["created_at"], FMT)
            svc = SERVICE_BY_CODE.get(r["service_code"], {"icon": "", "name": r["service_code"]})
            tri = f"{TRIAGE_ICON[r['triage_level']]} {TRIAGE_TEXT[r['triage_level']]}" if r["triage_level"] else "—"
            cells = [r["ticket_label"] + (" ✎" if r["modified_count"] else ""), f"{dt:%H:%M}", f"{dt:%d/%m/%Y}",
                     display_name(r), f"{svc['icon']} {svc['name']}", tri]
            for j, txt in enumerate(cells):
                it = QTableWidgetItem(txt); it.setData(Qt.ItemDataRole.UserRole, r["id"])
                if j == 5 and r["triage_level"]:
                    col = QColor(TRIAGE_COLORS[r["triage_level"]]); col.setAlpha(70); it.setBackground(col)
                self.table.setItem(i, j, it)
            if r["id"] == sel:
                self.table.selectRow(i)

    @guard
    def edit_selected(self, *_):
        aid = self.selected_id()
        if not aid:
            return self.show_banner("Sélectionnez d'abord une ligne dans l'historique.", "error")
        row = self.db.get(aid)
        dlg = EditDialog(row, self.codes if row["service_code"] in self.codes else self.codes + [row["service_code"]], self)
        if dlg.exec():
            new = self.db.update_admission(aid, dlg.values(), self.station)
            try:
                archive_reception(new)
            except OSError:
                pass
            self.refresh()
            if QMessageBox.question(self, "Ticket", "Réimprimer le ticket corrigé ?") == QMessageBox.StandardButton.Yes:
                print_ticket(self.cfg, new)

    @guard
    def reprint_selected(self, *_):
        aid = self.selected_id()
        if not aid:
            return self.show_banner("Sélectionnez d'abord une ligne dans l'historique.", "error")
        ok, msg = print_ticket(self.cfg, self.db.get(aid))
        if not ok:
            self.show_banner(f"Impression impossible : {msg}", "error")

    # ---------------- stats & compteurs ----------------
    @guard
    def refresh(self, *_):
        if not self.user:
            return
        self.refresh_history()
        sid = self.db.current_shift(self.station)
        s, info = self.db.stats(sid), self.db.shift_info(sid)
        start = datetime.strptime(info["started_at"], FMT)
        per = " · ".join(f"{SERVICE_BY_CODE[c]['icon']} {n}" for c, n in s["by_service"].items() if c in SERVICE_BY_CODE)
        self.stats.setText(f"👥 <b>Garde ({start:%d/%m %H:%M}) : {s['total']}</b> &nbsp;|&nbsp; 🔴 {s['ROUGE']} &nbsp; "
                           f"🟠 {s['ORANGE']} &nbsp; 🟢 {s['VERT']} &nbsp;|&nbsp; {per or 'aucun service enregistré'}")

    @guard
    def reset_counters(self, *_):
        m = QMessageBox.question(self, "Nouvelle garde",
                                 "Remettre tous les compteurs à zéro (début de garde) ?\nL'historique est conservé.")
        if m == QMessageBox.StandardButton.Yes:
            self.db.reset_shift(self.station)
            self.refresh()
            self.show_banner("Compteurs remis à zéro : nouvelle garde démarrée.")
