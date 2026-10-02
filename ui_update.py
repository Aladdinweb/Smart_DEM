"""Threads Qt pour ne jamais figer l'interface pendant la vérification / le téléchargement."""
from PyQt6.QtCore import QThread, pyqtSignal

import github_updater as gu


class CheckThread(QThread):
    done = pyqtSignal(object, str)      # (info, erreur)

    def __init__(self, repo):
        super().__init__(); self.repo = repo

    def run(self):
        try:
            self.done.emit(gu.check_latest(self.repo), "")
        except Exception as e:
            self.done.emit({}, str(e))


class DownloadThread(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(str, str)         # (chemin du zip, erreur)

    def __init__(self, info):
        super().__init__(); self.info = info

    def run(self):
        try:
            self.done.emit(gu.download_update(self.info, self.progress.emit), "")
        except Exception as e:
            self.done.emit("", str(e))
