"""Synchronisation en arrière-plan (offline-first) : les consultations clôturées sont mises en file (sync_outbox) puis envoyées
en HTTPS (FHIR Bundle) dès qu'Internet et un serveur sont disponibles. Désactivée par défaut : aucun serveur national n'existe encore."""
import json, threading, urllib.request


def run_once(db, endpoint, token, post=None, limit=20):
    """Envoie les éléments en attente. `post(url, body, headers)` est injectable (tests). Retourne (envoyés, échecs)."""
    post = post or _post
    sent = failed = 0
    for it in db.outbox_pending(limit):
        try:
            post(endpoint, it["payload"].encode("utf-8"), {"Content-Type": "application/fhir+json", "Idempotency-Key": f"dem-{it['id']}",
                                                            **({"Authorization": f"Bearer {token}"} if token else {})})
            db.outbox_mark(it["id"], True); sent += 1
        except Exception as e:
            db.outbox_mark(it["id"], False, str(e)[:200]); failed += 1
            if failed >= 3:      # pas d'Internet / serveur injoignable : on s'arrête, reprise au prochain cycle
                break
    return sent, failed


def _post(url, body, headers):
    if not url.lower().startswith("https://"):
        raise ValueError("HTTPS obligatoire pour la synchronisation.")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=15).close()


class SyncWorker(threading.Thread):
    def __init__(self, db, cfg, interval=60):
        super().__init__(daemon=True)
        self.db, self.cfg, self.interval, self.stop_evt = db, cfg, interval, threading.Event()

    def run(self):
        while not self.stop_evt.wait(self.interval):
            if self.cfg.get("sync_enabled") and self.cfg.get("sync_endpoint"):
                try:
                    run_once(self.db, self.cfg.get("sync_endpoint"), self.cfg.get("sync_token", ""))
                except Exception:
                    pass
