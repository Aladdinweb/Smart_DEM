"""Listes de saisie rapide (commodités de saisie, pas une référence pharmacologique : le médecin reste responsable)."""
EXAM_TYPES = ["Radio X", "Échographie", "Scanner"]
REGIONS = ["Thorax", "Abdomen", "Crâne", "Rachis cervical", "Rachis dorsal", "Rachis lombaire", "Bassin",
           "Membre supérieur", "Membre inférieur", "Épaule", "Genou", "Cheville", "Main / Poignet", "Pied",
           "Pelvis (échographie)", "Autre…"]
SIDES = ["Non applicable", "Droit", "Gauche", "Bilatéral"]
RADIO_STATUS = {"PENDING": "⏳ En attente", "CALLED": "📣 Patient appelé", "DONE": "✅ Terminé",
                "AWAITING_PRINT": "🖼 En attente de tirage", "CANCELLED": "✖ Annulé"}
POSOLOGIES = ["1 cp x 1/j (matin)", "1 cp x 1/j (soir)", "1 cp x 2/j", "1 cp x 3/j", "2 cp x 3/j",
              "1 gélule x 2/j", "1 gélule x 3/j", "1 sachet x 1/j", "1 sachet x 3/j", "1 c. à café x 3/j",
              "1 c. à soupe x 3/j", "1 ampoule x 1/j", "2 pulvérisations x 2/j", "1 application x 2/j", "si besoin"]
DURATIONS = ["3 jours", "5 jours", "7 jours", "10 jours", "15 jours", "1 mois", "3 mois", "Traitement continu"]
LAB_ITEMS = ["NFS (numération formule sanguine)", "Glycémie à jeun", "HbA1c", "Urée", "Créatinine",
             "Bilan lipidique (cholestérol, triglycérides)", "Transaminases (ASAT / ALAT)", "CRP", "VS",
             "Ionogramme sanguin", "Acide urique", "TSH", "ECBU", "Groupe sanguin / Rhésus", "Bilan de coagulation (TP / INR)",
             "Sérologie (à préciser)"]
DRUGS_SEED = [
    "Paracétamol 500 mg cp", "Paracétamol 1 g cp", "Ibuprofène 400 mg cp", "Diclofénac 50 mg cp",
    "Amoxicilline 500 mg gélule", "Amoxicilline 1 g cp", "Amoxicilline + acide clavulanique 1 g cp",
    "Azithromycine 500 mg cp", "Ciprofloxacine 500 mg cp", "Métronidazole 500 mg cp", "Céfixime 200 mg cp",
    "Oméprazole 20 mg gélule", "Pantoprazole 40 mg cp", "Métoclopramide 10 mg cp", "Dompéridone 10 mg cp",
    "Phloroglucinol 80 mg cp", "Loratadine 10 mg cp", "Cétirizine 10 mg cp", "Prednisolone 20 mg cp",
    "Salbutamol 100 µg spray", "Ambroxol sirop", "Carbocistéine sirop", "Metformine 850 mg cp",
    "Gliclazide 60 mg cp", "Amlodipine 5 mg cp", "Énalapril 20 mg cp", "Bisoprolol 5 mg cp", "Furosémide 40 mg cp",
    "Atorvastatine 20 mg cp", "Acide acétylsalicylique 100 mg sachet", "Fer + acide folique cp",
    "Cholécalciférol (vitamine D3) 100 000 UI amp", "Sérum physiologique unidoses", "Solution de réhydratation orale sachet",
    "Lévothyroxine 50 µg cp", "Mébendazole 100 mg cp", "Sulfate de zinc sirop", "Povidone iodée solution cutanée",
]
