# Smart DEM — Architecture de la v1.5.0 (document de conception)

> Statut : **conception, aucun code de la 1.5.0 n'est encore écrit.** Base : v1.4.0 (schéma v5). Ce document dit, pour chacun des 6 lots, ce qui existe déjà, ce qui manque, comment on le construit, et quelles **décisions** sont nécessaires avant de coder.

## 0. Constat sur la v1.4.0 (ce qui change la manière de faire)

| Lot | Déjà là | Manque réellement |
|---|---|---|
| 1. Matériel | Impression par `QPrinter` (pilote Windows) : tickets 58/80 mm, A4 ; QR (`qr.py`), Code 128 (`barcode.py`) ; lecteurs USB « mode clavier » saisis dans des champs dédiés (pharmacie, rendez-vous) | ESC/POS natif (octets bruts, coupe, rapidité, sans pilote) ; A5 ; **routage** « tel document → telle imprimante » ; lecteur actif quel que soit le champ ayant le focus |
| 2. Stock | **Rien** : la table `drugs` n'est qu'une liste d'autocomplétion (nom + compteur). Les ordonnances contiennent du texte libre, `pharmacy_dispense` ne change aucune quantité | Tout : articles, lots, péremptions, mouvements, seuils, alertes, décrément |
| 3. Statistiques | `stats_report` (Hub) + `ReportDialog` + rapport DSP mensuel automatique | **`stats_report` n'a aucun contrôle de rôle** (tout utilisateur connecté peut l'appeler) ; le bouton est dans Paramètres de **tous** les postes ; le rapport mensuel s'imprime sur le premier PC lancé |
| 4. En-tête | Logo officiel (v1.4.0), en-tête `parent - structure` (une seule langue) | Noms arabes, affichage FR + AR, propagation depuis le Hub, impressions |
| 5. National Ready | Hub Flask : `/rpc` (JWT utilisateur), `/api/ping`, `/api/tv/*` ; `fhir.py` (Patient, Encounter, MedicationRequest, ServiceRequest) ; `sync.py` (file d'envoi vers une URL) | API REST **versionnée** à jetons d'application, contrat JSON stable, couche « connecteur » ; **aucune** intégration CNAS/Chifa n'existe |
| 6. Sauvegarde / MAJ | `auto_backup` (quotidienne + fin de garde, 14 copies dans `backups/`) ; `updater.py` (mise à jour depuis dossier / zip, fichiers de données protégés) ; `github_updater.py` (téléchargement GitHub, poste par poste) | Sauvegarde **chiffrée, vérifiée, copiée hors du disque** ; diffusion Hub → clients sur le LAN **avec signature** ; compatibilité de versions Hub/clients |

## 1. Principes communs
1. **Additif** : schéma v6 par migration idempotente (sauvegarde préalable, comme v4→v5). Aucune donnée existante n'est modifiée.
2. **Le Hub fait foi** : toute règle (droits, stock, stats) est contrôlée **côté Hub** dans `database.py` (`_require`), jamais seulement en masquant un bouton.
3. **Peu de dépendances** : ESC/POS, API REST, sauvegarde : bibliothèque standard + `cryptography` (déjà présente). Pas de nouvelle dépendance lourde dans le `.exe`.
4. **Un lot = un jeu de tests** (comme v1.4.0) ; le matériel réel n'est pas testable ici : chaque lot matériel prévoit un **mode simulation** et un **test d'impression / de lecture** dans Paramètres.
5. **Compatibilité** : `api_level` annoncé par `/api/ping` ; un client plus ancien que `min_client` du Hub est refusé avec un message clair (évite les demi-mises à jour).

## 2. Lot 1 — Matériel (impression ESC/POS, A4/A5, lecteurs)
**Modules** : `hw_escpos.py` (encodeur + transports), `print_router.py` (choix de l'imprimante), `scan.py` (routeur de lecteur).

- **Encodeur ESC/POS interne** (≈150 lignes) : initialisation, alignement, gras, QR natif (`GS ( k`) ou image, code-barres, **coupe**. Le texte **arabe n'est pas envoyé en texte** (jeux de caractères peu fiables) : le ticket est dessiné par Qt en image 1 bit (largeur 384 pts = 58 mm, 576 pts = 80 mm) puis envoyé en raster (`GS v 0`). Avantage : français + arabe + logo + QR identiques à l'écran.
- **Transports** : (a) **spooler Windows en mode RAW** (via `winspool` / `ctypes`, aucune dépendance) — cas le plus courant en USB ; (b) **réseau TCP :9100** ; (c) **port série/COM** (adaptateurs). Le mode `QPrinter` actuel reste en repli.
- **Routage** (`config["printers"]`) : `ticket → thermique (58/80, transport, coupe)`, `ordonnance → A5`, `certificat → A4`, `rapport → A4`. Pages **A5** ajoutées à `printer.py`. Un poste sans imprimante thermique continue d'imprimer en PDF/A4.
- **Lecteurs** : `scan.py` détecte une **rafale de frappes** (< 30 ms entre caractères + terminateur Entrée/Tab) quel que soit le champ actif, puis route par préfixe : `SDEM1…` (ordonnance), `SDEMR1…` (rendez-vous), Code 128C (n° de ticket). Réglages : suffixe, préfixe, délai. Le champ de saisie n'a plus besoin d'avoir le focus. Les lecteurs 2D lisent déjà les QR actuels.
- **Paramètres › Matériel** : choix par type de document, largeur papier, **test d'impression**, **test de lecture**.
- **Risques** : modèles réels inconnus (Epson TM-T20/T88, Xprinter, etc., commandes QR légèrement différentes) → prévoir un champ « profil » ; la coupe/QR natif doivent être validés sur vos imprimantes.

## 3. Lot 2 — Stock local & pharmacie
**Schéma v6 (nouveau)**
```sql
items(id, kind CHECK IN ('DRUG','CONSUMABLE'), name, form, unit, min_stock, active, UNIQUE(name,form))
stock_lots(id, item_id, lot_no, expiry DATE, qty_in, qty_left, received_at, supplier)
stock_moves(id, item_id, lot_id, qty_delta, reason CHECK IN ('RECEIPT','DISPENSE','CARE','ADJUST','WASTE','EXPIRED','RETURN'),
            ref_kind, ref_id, user_id, at, note)           -- ajout seul, comme `acts`
act_consumption(act_label, item_id, qty)                    -- consommables par acte de soins (modifiable par la pharmacie / coordination)
```
- **Rapprochement ordonnance ↔ article** : aujourd'hui une ligne d'ordonnance est du **texte libre**. On ajoute `item_id` (facultatif) à la saisie du médecin via l'autocomplétion (nomenclature importée → `items`) ; sans `item_id`, la délivrance demande au pharmacien de choisir l'article.
- **Décrément automatique** :
  - `pharmacy_dispense(uid, lines)` : le pharmacien valide les **quantités réellement délivrées** (boîtes/unités ; la posologie ne donne pas le nombre de boîtes) ; une transaction crée les mouvements `DISPENSE` et met à jour les lots.
  - `record_act(...)` : les consommables de `act_consumption` sont décomptés (`CARE`) à l'enregistrement de l'acte.
  - **FEFO** : on prélève d'abord le lot qui périme le plus tôt ; un lot périmé n'est jamais prélevé.
  - Tout dans la **même transaction SQLite** que l'acte (pas de décalage possible).
- **Alertes** : `stock_alerts()` → `{rupture, sous_minimum, perime, perime_bientot (90 j / 30 j)}` ; affichées dans la fenêtre Pharmacie, la coordination (vue d'ensemble), et un bandeau à la connexion des responsables.
- **Écrans** : Pharmacie → onglets **Stock** (entrées, inventaire, ajustements motivés, mise au rebut), **Alertes** ; import CSV des articles/lots.
- **Droits** : pharmacie = tout ; coordinateurs = lecture + alertes ; autres = aucun accès.
- **Décisions à prendre** : (1) *stock négatif* : bloquer la délivrance, ou autoriser avec alerte ? (2) liste initiale des consommables par acte (injection, pansement, suture…) ; (3) stock unique ou **par service** (ex. salle de soins) ? (proposition : unique, puis sous-stock plus tard).

## 4. Lot 3 — Statistiques réservées aux responsables
- **Qui** : coordinateurs (COORDINATEUR DES MÉDECINS, COORDINATEUR DE PARAMÉDICAL) et **administrateur**. Aujourd'hui « l'administrateur » = un **PIN local** à chaque PC, que le Hub ne peut pas vérifier. Proposition : `admin_login(pin)` **sur le Hub** → jeton JWT de rôle `admin` valable 15 min (le PIN et son sel migrent dans la base du Hub).
- **Serveur** : `_require_manager(user_id)` appliqué à `stats_report`, `stock_report`, exports ; test « chaque rôle non autorisé reçoit `PermissionError` ».
- **Interface** : retrait de « Rapports statistiques DSP » de Paramètres pour les postes non responsables ; nouvel onglet **📊 Statistiques** dans les fenêtres des coordinateurs ; accès administrateur via Paramètres + PIN Hub.
- **Rapport mensuel automatique** : généré **uniquement par le Hub** (plus par le premier PC lancé).
- **À trancher** : les compteurs de garde (barre d'état « Garde : n ») restent visibles de tous (opérationnels) ; seuls les **rapports et agrégats globaux** sont restreints.

## 5. Lot 4 — En-tête bilingue dynamique
- **Données** : `meta` du Hub : `establishment = {parent_fr, parent_ar, structure_fr, structure_ar, address, …}` (RPC `get_establishment` public, `set_establishment` administrateur). Les clients **n'ont plus leur propre copie** : ils la lisent au démarrage et à chaque `establishment_rev` modifié dans `/api/ping` (mise à jour dynamique sans redémarrage).
- **Affichage** : `HeaderBar` = ligne FR, **juste en dessous** ligne AR (texte `RightToLeft`, police à glyphes arabes : Segoe UI / Tahoma / Noto Naskh en repli). Mêmes deux lignes dans `header_html`, `ticket_html`, ticket RDV, certificats, rapports (balise `dir="rtl"`), et dans le raster ESC/POS.
- **Saisie** : Paramètres (administrateur) et assistant de première installation ; `structures.json` reçoit un champ `ar`. Logo : déjà intégré en v1.4.0 (`assets/logo_ministere.png`).
- **Risque** : mise en forme bidirectionnelle des impressions → vérifiée par captures/PDF dans les tests.

## 6. Lot 5 — Interconnexion nationale simplifiée
**Ce qui est réalisable sans spécification officielle** : l'architecture d'accueil. **L'intégration CNAS/Chifa elle-même ne peut pas être écrite sans leur cahier des charges, une convention et des identifiants** — elle n'est pas dans mes connaissances vérifiables et ne doit pas être devinée.
- **API REST v1** (`api_v1.py`, Blueprint Flask monté sur le Hub, `/api/v1/…`) : `GET /health`, `/patients/{id}`, `/encounters`, `/prescriptions/{uuid}`, `/stock/items`… JSON UTF-8, dates ISO 8601, pagination, codes d'erreur homogènes, **version dans l'URL**.
- **Contrat de données** : FHIR R4 (déjà amorcé dans `fhir.py`) comme format canonique ; schémas JSON publiés dans `docs/api/`.
- **Sécurité** : **clés d'application** distinctes des comptes utilisateurs (stockées hachées, portées = lecture seule par défaut, expiration, liste d'adresses IP autorisées), HTTPS obligatoire hors LAN, **journal d'audit** de chaque appel ; données minimales (pas d'observations libres ni de psychologie).
- **Sortie** : `connectors/` avec une interface `Connector` (`send(event)`, `healthcheck()`), alimentée par la file existante de `sync.py` (idempotence par clé d'événement, reprise après coupure) ; un connecteur `chifa` **vide, désactivé**, documenté « en attente de spécification ».
- **À vérifier avec un juriste / l'autorité compétente** avant tout échange réel : cadre légal de protection des données personnelles de santé en Algérie (loi 18-07) et convention CNAS.

## 7. Lot 6 — Sauvegarde automatique & mise à jour LAN
### 7.1 Sauvegarde
- Déjà : quotidienne + fin de garde, 14 copies. **Ajouts** : (1) planificateur **côté Hub uniquement** à heure fixe (réglable, ex. 02:00) avec rattrapage au démarrage ; (2) **répertoire sécurisé** configurable (droits restreints au compte de service) ; (3) copie **chiffrée AES-256-GCM** avec la clé `db.key` + empreinte SHA-256 dans un `manifest.json` ; (4) **vérification** après chaque sauvegarde (`PRAGMA integrity_check` sur la copie) ; (5) rétention **7 quotidiennes + 4 hebdomadaires + 12 mensuelles** ; (6) **seconde destination** (disque USB / partage réseau) ; (7) alerte coordination si la dernière sauvegarde vérifiée a plus de 26 h ; (8) assistant de **restauration** documenté. *La clé de chiffrement doit être conservée hors du poste (déjà exportable dans Paramètres) — sans elle, la sauvegarde chiffrée est inutilisable.*
### 7.2 Mise à jour LAN
```
GitHub Release ──(Hub : github_updater)──► Hub/updates/{version}/ (zip + manifest.json + manifest.sig)
Clients ──GET /api/update/manifest──► comparaison de version ──GET /api/update/package──► vérification ──► installation
```
- `manifest.json` : `{version, sha256, size, min_api_level, notes}` ; **signature Ed25519** du manifeste par **votre clé de publication** (clé privée jamais dans le dépôt ni sur le Hub ; clé publique **embarquée** dans l'exécutable). Un client **refuse tout paquet non signé** : sans cela, quiconque possède le jeton réseau pourrait faire exécuter du code sur tous les postes.
- Client : vérifie au lancement et toutes les 6 h ; télécharge en arrière-plan ; vérifie SHA-256 **et** signature ; propose l'installation **à la prochaine déconnexion** (jamais en pleine consultation) ; réutilise `updater.build_update_script` (données protégées, sauvegarde avant) ; **retour arrière** : l'ancienne version est conservée jusqu'au premier démarrage réussi.
- Hub : seul à contacter GitHub ; ordre recommandé : **Hub d'abord**, puis clients (le handshake `api_level` empêche les mélanges dangereux).

## 8. Fichiers et API prévus
- **Nouveaux modules** : `hw_escpos.py`, `print_router.py`, `scan.py`, `stock.py` (+ `ui_stock.py`), `api_v1.py`, `connectors/`, `backup.py`, `lan_update.py`, `ui_stats.py`.
- **RPC ajoutées** (liste fermée `RPC_METHODS`) : `admin_login`, `get_establishment`, `set_establishment`, `stock_*` (items, lots, receive, adjust, alerts, report), `pharmacy_dispense` (signature étendue), `backup_status`, `backup_now`, `update_status`.
- **Schéma v6** : tables du §3 ; `meta` : `establishment`, `admin_pin_*`, `api_keys` (table `api_keys`), `update_state`.
- **Migration v5 → v6** + fixture `schema_v5.sql` + tests de migration (comme v4→v5).

## 9. Ordre de réalisation conseillé (chaque étape = tag testable)
| Étape | Contenu | Pourquoi dans cet ordre |
|---|---|---|
| 1.5.0-a | Lot 3 (stats) + Lot 4 (bilingue) | Petits, sans matériel, corrigent un défaut réel (stats ouvertes à tous) |
| 1.5.0-b | Lot 6 (sauvegarde chiffrée + mise à jour LAN signée) | Sécurise les mises à jour **des lots suivants** |
| 1.5.0-c | Lot 2 (stock) | Le plus gros ; touche pharmacie, soins, ordonnances |
| 1.5.0-d | Lot 1 (ESC/POS, A5, lecteurs) | Dépend du matériel disponible pour valider |
| 1.5.0-e | Lot 5 (API REST + connecteurs) | Contrat stable seulement quand le reste l'est |

## 10. Décisions (réponses reçues : 1 = retrait de stock · 2 = administrateur vérifié par le Hub · 3 = stock négatif autorisé avec alerte orange/rouge · 4 = thermique 80 mm ESC/POS USB/LAN, A4/A5 pilotes Windows · 5 = socle API + connecteur Chifa vide · 6 = clé de signature gardée par l'administrateur hors dépôt · 7 = consommables par défaut fournis · 8 = noms officiels FR/AR fournis)

*Lot a livré : voir `STATE.md` §00. Questions d'origine, pour mémoire :*
1. « Dépréciation automatique » = **décrémenter le stock** (et non une dépréciation comptable) : confirmé ?
2. **Administrateur** : accepter un compte administrateur vérifié par le Hub (PIN migré) ?
3. **Stock négatif** : bloquer ou autoriser avec alerte ?
4. **Imprimantes thermiques** : marque/modèle, largeur 58 ou 80 mm, USB ou réseau ? Imprimante A4/A5 : modèle ?
5. **Chifa/CNAS** : disposez-vous du cahier des charges et d'une convention ? Sinon seul le socle (API + connecteur vide) est livré.
6. **Clé de signature des mises à jour** : qui la génère et la garde ? (je fournis le script de signature, elle ne doit jamais être dans GitHub)
7. **Consommables par acte de soins** : qui fournit la liste initiale ?
8. Noms **officiels arabes** exacts de l'établissement et de la tutelle (à saisir dans Paramètres, mais utiles pour les tests).

## 11. Critères d'acceptation
Droits vérifiés côté Hub pour chaque lot ; migration v5→v6 sur une copie de base réelle ; aucune régression des 67 tests existants ; impression réelle d'un ticket QR + A5 + A4 et lecture QR vérifiées sur le matériel ; sauvegarde restaurée **avec succès** sur un poste de test ; mise à jour LAN d'un client de test, avec refus d'un paquet falsifié.
