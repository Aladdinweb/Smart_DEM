"""Export HL7 FHIR R4 (squelette d'interopérabilité) : Patient, Encounter, MedicationRequest, ServiceRequest.
Aucune certification ni intégration CHIFA/CNAS/CASNOS : ce module prépare uniquement l'échange (voir STATE.md)."""
import hashlib

SYSTEM = "urn:smartdem"


def _pid(adm):
    key = adm.get("patient_ident") or f"{adm.get('name_norm')}|{adm.get('gender')}|{adm.get('birth_year')}"
    return "p-" + hashlib.sha256(key.encode()).hexdigest()[:20]


def _iso(ts):
    return ts.replace(" ", "T").split(".")[0] if ts else None


def patient(adm):
    p = {"resourceType": "Patient", "id": _pid(adm), "name": [{"family": adm.get("last_name") or "", "given": [adm.get("first_name") or ""]}],
         "gender": "male" if adm.get("gender") == "H" else "female", "birthDate": adm.get("birth_date") or str(adm.get("birth_year"))}
    if adm.get("patient_ident"):
        p["identifier"] = [{"system": f"{SYSTEM}:identifiant-patient", "value": adm["patient_ident"]}]
    return p


def consultation_bundle(d):
    cons, adm, doc = d["consultation"], d["patient"], d.get("doctor") or {}
    pid, eid = _pid(adm), f"e-{cons['id']}"
    ref_p, ref_e = {"reference": f"Patient/{pid}"}, {"reference": f"Encounter/{eid}"}
    prac = {"display": f"Dr {doc.get('last_name', '')} {doc.get('first_name', '')}".strip()}
    res = [patient(adm),
           {"resourceType": "Encounter", "id": eid, "status": "finished", "class": {"code": "AMB"}, "subject": ref_p,
            "period": {"start": _iso(cons["started_at"]), "end": _iso(cons.get("ended_at"))},
            "reasonCode": [{"text": cons.get("diagnosis") or ""}], "participant": [{"individual": prac}]}]
    for rx in d.get("prescriptions", []):
        for i, it in enumerate(rx["items"]):
            res.append({"resourceType": "MedicationRequest", "id": f"mr-{rx['uuid'][:12]}-{i}", "status": "active", "intent": "order",
                        "identifier": [{"system": f"{SYSTEM}:ordonnance", "value": rx["number"]}],
                        "medicationCodeableConcept": {"text": it["drug"]}, "subject": ref_p, "encounter": ref_e,
                        "authoredOn": _iso(rx["created_at"]), "requester": prac,
                        "dosageInstruction": [{"text": f"{it['dosage']} — {it['duration']}".strip(" —")}]})
    for r in d.get("radiology", []):
        res.append({"resourceType": "ServiceRequest", "id": f"sr-rad-{r['id']}", "status": "completed" if r["status"] in ("DONE", "AWAITING_PRINT") else "active",
                    "intent": "order", "category": [{"text": "Imagerie"}], "code": {"text": f"{r['exam_type']} {r['region']} {r['side']}".strip()},
                    "subject": ref_p, "encounter": ref_e, "authoredOn": _iso(r["created_at"]), "note": [{"text": r.get("clinical_info") or ""}]})
    for l in d.get("lab_requests", []):
        res.append({"resourceType": "ServiceRequest", "id": f"sr-lab-{l['id']}", "status": "completed" if l["status"] == "DONE" else "active",
                    "intent": "order", "category": [{"text": "Biologie"}], "code": {"text": ", ".join(l["items"])},
                    "subject": ref_p, "encounter": ref_e, "authoredOn": _iso(l["created_at"])})
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        {"resource": r, "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"}} for r in res]}
