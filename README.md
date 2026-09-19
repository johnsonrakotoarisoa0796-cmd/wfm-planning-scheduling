# WFM Planning & Scheduling

Plateforme de planification, capacity planning, forecasting et suivi opérationnel
pour une activité de centre de contacts (LTF Monthly → STF Weekly → Daily/Intraday
→ Actual Performance).

> V1 sans IA. Conçue pour permettre l'ajout futur d'un moteur de forecasting ML
> sans réécrire l'application (voir `WFM_ARCHITECTURE_PLAN.md`).

## Architecture

Le document de référence complet (modèle de données, formules KPI, moteur
Erlang C, moteur Overtime, plan d'implémentation par étapes) se trouve dans
[`WFM_ARCHITECTURE_PLAN.md`](./WFM_ARCHITECTURE_PLAN.md).

Stack : FastAPI + SQLModel + PostgreSQL (Supabase) + Jinja2 + Chart.js,
déployé sur Render.

```
app/
├── main.py            # point d'entrée FastAPI
├── core/               # config, database, sécurité, unités
├── models/             # SQLModel (ajoutés au commit 02)
├── schemas/             # Pydantic I/O
├── services/            # toute la logique métier (forecast, kpi, erlang, overtime, ...)
├── routers/              # un router par module (dashboard, ltf, stf, daily, ...)
├── templates/            # Jinja2
└── static/               # css, js, Chart.js
```

## Installation locale

```bash
python -m venv .venv
source .venv/bin/activate  # ou .venv\Scripts\activate sous PowerShell
pip install -r requirements.txt
cp .env.example .env       # puis renseigner DATABASE_URL (Supabase) et SECRET_KEY
uvicorn app.main:app --reload
```

L'application démarre sur `http://127.0.0.1:8000`. Vérifier `/health`.

## Variables d'environnement

| Variable | Description | Défaut |
|---|---|---|
| `ENV` | `development` ou `production` | `development` |
| `DATABASE_URL` | URL de connexion PostgreSQL (Supabase) | — |
| `SECRET_KEY` | Clé secrète pour les sessions | — |
| `SECURE_COOKIES` | `true` en prod (https), `false` en dev local (http) | `true` |
| `DAILY_HOURS` | Heures de travail par jour | `8` |
| `WEEKLY_HOURS` | Heures de travail par semaine | `40` |
| `WORKING_DAYS` | Jours travaillés par semaine | `5` |
| `INTERVAL_MINUTES` | Granularité des intervalles intraday | `30` |

Ne jamais committer `.env`. Sur Render, ces variables sont définies dans le
dashboard du service (voir `render.yaml`).

## Base de données

PostgreSQL via Supabase, migrations gérées par Alembic. Les modèles et la
première migration seront ajoutés au commit 02.

## Authentification

Sessions cookie signées (`itsdangerous`) + hashing bcrypt (`passlib`) + RBAC
(`admin / wfm_analyst / team_lead / viewer`) + TOTP (2FA) obligatoire dès la
V1. Pas d'inscription libre : les comptes sont créés par un administrateur.

**Créer le premier compte admin** (après `alembic upgrade head`) :
```bash
python -m app.scripts.create_admin
```
Le script demande email + mot de passe, puis affiche un QR code ASCII à
scanner avec Google Authenticator / Authy (ou la clé à saisir manuellement).

**Connexion** : `/login` (email + mot de passe) → `/login/verify` (code à 6
chiffres) → session ouverte. CSRF protégé sur tous les formulaires POST
(pattern double-submit cookie, sans stockage serveur).

**RBAC** : les routes protégées utilisent les dependencies FastAPI
`require_login` et `require_role(...)` (voir `app/core/security.py`), jamais
de vérification de rôle inline dans les routers.

## Moteur KPI

Toutes les formules WFM (`app/services/kpi_service.py`) : AHT, Handle Time,
Occupancy, Service Level, ASA, Shrinkage %, Paid/Productive/Production
Hours, Forecast Accuracy, Staffing Gap, et un statut générique
(`on_target` / `warning` / `critical`) pour l'affichage Dashboard (§5).
37 tests unitaires couvrent chaque formule, y compris les cas de division
par zéro (période sans activité).

## Moteur Erlang C

`app/services/erlang_service.py` — calcul du Required HC (§18), isolé,
sans dépendance DB/FastAPI. Erlang B par récurrence (jamais la formule
factorielle classique, qui déborde numériquement bien avant les effectifs
réels d'un centre de contacts — validé jusqu'à 800+ Erlangs sans problème).

Formules vérifiées contre un calculateur Erlang C tiers indépendant : 100
appels/30 min, AHT 180s = 10 Erlangs, 14 agents → 88.84% de service level
et ~7.8s d'ASA (13 agents → 79.56%, sous la cible). 22 tests unitaires.

## Module LTF Monthly

Premier module métier avec UI complète (`/ltf`) : liste filtrable (année,
campagne, skill), création, détail avec historique des versions. Réservé
en écriture aux rôles `admin`/`wfm_analyst` ; lecture ouverte à tous les
connectés.

**Pipeline de calcul** (`app/services/forecast_service.py`), jamais de
formule inline dans le router ou le template :
Workload Hours → Net Required HC (formule agrégée, pas Erlang C — voir
`kpi_service.required_hc_aggregate`) → Gross Required HC (shrinkage
appliqué via `erlang_service.apply_shrinkage`) → Paid/Productive/Production
Hours. `staffing_gap` et `overtime_required_hours` restent à 0 à la
création : ils seront calculés par Capacity Planning (commit 09) et
Overtime (commit 11), qui ont besoin de l'effectif réel.

**Versioning (§9)** : créer un LTF pour une période déjà existante ne
l'écrase jamais — une nouvelle version est créée, l'ancienne passe
`is_current=False` mais reste consultable via l'historique.

Pas encore de page d'administration Campaigns/Skills : utiliser
`python -m app.scripts.seed_demo_data` pour créer des données de test.

## Module STF Weekly

`/stf` — réajustement hebdomadaire d'un LTF déjà existant (§8). La création
échoue explicitement si aucun LTF actif ne couvre le mois de la semaine ISO
choisie ("créez d'abord un LTF pour ce mois") : le STF n'existe pas seul,
il réajuste toujours un plan de référence.

La page de détail affiche le tableau **LTF vs STF vs Variance** de
l'exemple du cahier des charges (`Adjustment = STF − LTF`,
`Adjustment % = (STF − LTF) / LTF × 100`) — testé mot pour mot contre cet
exemple chiffré. Le LTF affiche en retour la liste de ses réajustements
STF liés.

Même règle de versioning que le LTF : un second STF pour la même semaine
ISO ne remplace jamais le premier.

## Module Daily / Intraday

`/daily` — granularité 30 minutes (§10). **C'est ici qu'Erlang C
(`erlang_service.find_required_agents`) s'applique enfin intervalle par
intervalle**, contrairement au LTF/STF qui utilisent une formule agrégée
(la dynamique d'arrivée des appels sur une fenêtre courte justifie
réellement la théorie des files d'attente à ce niveau — voir le docstring
de `intraday_service.py`).

**Génération** : un volume + AHT journaliers sont répartis sur 48 tranches
via un profil de distribution par défaut (deux pics matin/après-midi,
somme exactement 100%, voir `default_intraday_profile_pct()`) — pas de
saisie manuelle de 48 valeurs. Le HC requis est recalculé par Erlang C
pour *chaque* intervalle, donc varie réellement avec le trafic (testé
explicitement : le pic a un required_hc supérieur au creux).

**Actuals** : Service Level/ASA/Occupancy "atteints" sont des **estimations
via Erlang C appliquée aux valeurs réelles** (volume/AHT/HC saisis), pas
une mesure ACD directe — la V1 n'a pas d'intégration avec un vrai
distributeur d'appels (l'import de données du §36 viendra plus tard).
Modification réservée à `admin`/`wfm_analyst`/`team_lead` (le pilotage
opérationnel au jour le jour n'exige pas de construire les forecasts long
terme) ; génération réservée à `admin`/`wfm_analyst`.

Régénérer une journée déjà générée échoue explicitement — pas d'écrasement
silencieux.

## Module Capacity Planning

`/capacity` — projection HC (§31). Contrairement au LTF/STF, **pas de
versioning** : ré-enregistrer un plan pour la même période/campagne/skill
met à jour l'existant plutôt que d'empiler des versions (même logique que
la saisie d'actuals en Daily/Intraday) — c'est un suivi opérationnel de
l'état RH courant, pas un forecast.

`Future HC = Current HC + Recrutements + Transferts entrants − Transferts
sortants − Attrition − Absentéisme` (les deux derniers en % du Current
HC). Le Required HC est extrait du LTF actif de la période (instantané au
moment de l'enregistrement) — la création échoue sans LTF actif, même
principe de dépendance explicite que le STF. La fiche détail affiche le
Gap actuel *et* projeté, chacun avec un statut visuel
(overstaffed/balanced/understaffed).

## Module Shrinkage

`/shrinkage` — enregistrement + rapport (§23-§25). Indoor (Break, Meeting,
Personal Time, Outage, Project, Training) et Outdoor (Leave, Absenteeism)
sont créées par défaut au démarrage (`bootstrap_shrinkage_categories`,
inconditionnel — contrairement aux bootstraps admin/démo, ce sont des
catégories de référence standard, pas des données de démonstration).

**Une seule page de rapport** sert les trois granularités du cahier des
charges (Monthly/Weekly/Daily) : l'utilisateur choisit une plage de dates
libre plutôt que trois pages qui feraient le même calcul. Paid Hours est
basé sur l'effectif **actif réellement rattaché au skill** (via
EmployeeSkill), pas le HC théorique d'un forecast LTF/STF.

Contrairement au LTF/STF/Capacity, aucune contrainte d'unicité : un même
employé peut avoir plusieurs enregistrements le même jour (une pause ET
une réunion). Enregistrement ouvert à `admin`/`wfm_analyst`/`team_lead`
(même RBAC que les actuals Daily/Intraday).

## Module Overtime

`/overtime` — Required OT calculé, Actual OT saisi séparément, **jamais
confondus** (§30, exactement comme promis depuis les commits 06/07).

Required Hours et Available Hours viennent directement des intervalles
Daily/Intraday déjà générés (`somme(Required HC × 0,5h)` et
`somme(Scheduled HC × 0,5h)`) — **une seule fonction de calcul** sur une
plage de dates arbitraire sert Daily/Weekly/Monthly (§27-29), même
principe que le rapport Shrinkage. `OT Required = max(0, Required −
Available)` ; jamais négatif, un excédent est un problème de sur-staffing
(Capacity Planning), pas un "OT négatif".

**Premier vrai graphique Chart.js de l'app** : la fiche détail affiche OT
Required par jour (§29) quand la période couvre plusieurs jours.

Actual OT (une fois connu — pas d'intégration paie en V1) se saisit
séparément et ne modifie jamais Required ; la fiche détail calcule alors
OT Variance = Actual − Required. Saisie ouverte à
`admin`/`wfm_analyst`/`team_lead` ; création d'un plan réservée à
`admin`/`wfm_analyst`.

## Module Scheduling

`/scheduling` — shifts configurables, affectations par agent, impact des
pauses sur le staffing (§33-34).

**Shifts** (`/scheduling/shifts`) : gabarits d'horaires (nom, début, fin,
pause, déjeuner). Les shifts chevauchant minuit (ex: 17:00→02:00, cité en
exemple au §33) sont gérés explicitement — `start_time > end_time` signale
ce cas, testé pour chaque intervalle de la nuit.

**Affectations** (`/scheduling`) : un agent a **un seul planning par
jour** — ré-enregistrer pour la même date met à jour l'affectation
existante (comme Capacity/Overtime, pas comme Shrinkage).

**Impact des pauses** (`/scheduling/breaks`) : pour chaque intervalle de
30 min, Available HC avant/après pause comparé au Required HC (repris du
forecast Daily/Intraday si disponible) — révèle les sous-staffing créés
par des pauses mal réparties (ex: toute une équipe en pause en même
temps). Réutilise la même grille de 48 intervalles que Daily/Intraday,
partagée plutôt que dupliquée.

## Dashboard

`/` redirige désormais vers `/dashboard` (comme promis depuis le commit
06). Vue consolidée Current/Target/Variance/Status (§5) pour une
date/campagne/skill — **aucun nouveau calcul métier** : ce module assemble
ce que les autres produisent déjà (`kpi_service.evaluate_kpi`, construit
au commit 04, enfin utilisé).

Sections qui apparaissent/disparaissent selon ce qui existe déjà :
- **Volume** (Forecast/Actual/Accuracy) et **KPI vs Target** (Service
  Level, Occupancy, AHT, ASA, Shrinkage) : nécessitent un LTF actif *et*
  des actuals saisis sur la journée (Daily/Intraday) — sans actuals, les
  lignes n'apparaissent simplement pas plutôt que d'afficher des zéros
  trompeurs.
- **Staffing** (Required/Scheduled/Actual/Gap) : dès qu'une journée est
  générée, même sans actuals.
- **Capacity Planning** : seulement si un plan existe pour ce mois.
- **Overtime Required** : toujours calculé en direct pour le jour choisi.

Des bannières explicites indiquent quoi faire quand une source manque
("Aucun LTF actif", "Aucun intervalle généré") plutôt que de masquer
silencieusement des sections.

## Tests

```bash
pytest tests/unit          # AHT, Erlang, Shrinkage, Overtime, Occupancy, SL, ASA...
pytest tests/integration   # DB, API, Dashboard, Forecast
```

## Déploiement Render

1. Créer un nouveau service Web sur Render, connecté à ce repository GitHub.
2. Créer une base Supabase et récupérer la connection string.
3. Renseigner les variables d'environnement (`DATABASE_URL`, `SECRET_KEY`, ...).
4. Render utilise `render.yaml` pour la configuration du build/start et le
   health check (`/health`). Le start command lance `alembic upgrade head`
   avant `uvicorn` à chaque déploiement — nécessaire car le plan free de
   Render n'offre pas d'accès shell pour lancer les migrations à la main.

### Créer le premier compte admin sans accès shell

Deux options :
- **Local** (si vous avez un accès direct à `DATABASE_URL`) :
  `python -m app.scripts.create_admin` (voir section Authentification).
- **Sans accès shell (Render free)** : définir `BOOTSTRAP_ADMIN_EMAIL` et
  `BOOTSTRAP_ADMIN_PASSWORD` dans les variables d'environnement Render, puis
  redéployer. Un compte admin est créé automatiquement au démarrage
  (`app/main.py:bootstrap_admin_if_configured`), et le secret TOTP (QR code
  ASCII + clé manuelle) s'affiche dans les logs Render (Dashboard > Logs).
  Idempotent — les variables peuvent rester en place ou être retirées après
  coup, sans risque de recréer/réinitialiser le compte à chaque redémarrage.

### Créer une campagne/skill de démo sans accès shell

Même principe : définir `BOOTSTRAP_DEMO_DATA=true` dans les variables
d'environnement Render, puis redéployer. Crée une campagne + skill de
démo (`app/main.py:bootstrap_demo_data_if_configured`) si aucune campagne
n'existe encore — idempotent, ne duplique rien si une campagne a déjà été
créée (manuellement ou par un déploiement précédent).

### Réinitialiser la 2FA d'un compte existant sans accès shell

[#réinitialiser-la-2fa-dun-compte-existant-sans-accès-shell](#réinitialiser-la-2fa-dun-compte-existant-sans-accès-shell)

Le secret TOTP d'un compte n'est affiché qu'une seule fois, dans les logs
au moment de sa création (`create_admin` ou le bootstrap admin ci-dessus).
S'il a été perdu — logs Render expirés, QR jamais scanné, authenticator
changé de téléphone — aucun code ne peut plus jamais être validé pour ce
compte, quelle que soit l'exactitude de la saisie.

Définir `RESET_TOTP_EMAIL` (email du compte concerné) dans les variables
d'environnement Render puis redéployer régénère son secret TOTP
(`app/main.py:bootstrap_reset_totp_if_configured`) et l'affiche dans les
logs (Dashboard > Logs), comme au premier bootstrap.

**Contrairement aux autres bootstraps, celui-ci n'est pas idempotent** :
il régénère un nouveau secret à chaque démarrage tant que la variable
reste définie. Retirez `RESET_TOTP_EMAIL` dès que le nouveau secret a été
capturé, avant le prochain redéploiement — sinon le compte se
re-désynchronise de l'authenticator à chaque redémarrage.

## Historique d'implémentation

Voir `WFM_ARCHITECTURE_PLAN.md` section 11 pour le détail des 16 commits
prévus, du squelette initial jusqu'au durcissement de production.

## Règles Workforce / Payroll

La V1 distingue les heures contractuelles, l'amplitude de présence et la disponibilité opérationnelle.

- Contrat standard : 40 h/semaine sur 5 jours ouvrés, soit 8 h/jour.
- Déjeuner standard : 60 min, hors heures contractuelles.
- Deux pauses de 15 min sont configurables par shift.
- Une pause payée est incluse dans les 8 h contractuelles.
- Une pause non payée allonge l'amplitude sans augmenter les heures payées.
  Exemple : 07:00–16:00 avec 2 pauses payées + 1 h déjeuner = 8 h payées.
  Avec 2 pauses non payées, l'amplitude correspondante devient 07:00–16:30 pour conserver 8 h payées.
- Les agents ont un fuseau horaire IANA (par ex. America/New_York ou Europe/Paris).
  Les fenêtres saisonnières sont 07:00–01:00 en période DST et 08:00–02:00
  hors DST, avec conversion UTC automatique.
- Les absences gérées nativement sont : maternité, disponibilité, congé payé
  et congé sans solde. Le champ paid sépare rémunération et disponibilité
  opérationnelle : une absence payée consomme des heures payées mais retire
  de la capacité ; une absence non payée retire aussi les heures payées.
- Le Planner exclut les agents déjà planifiés et les agents absents de la
  capacité disponible avant de proposer un mix de shifts.

Les règles restent configurables : il n'est donc pas nécessaire de dupliquer
la logique métier pour créer un autre contrat, un autre nombre de pauses ou
un autre fuseau.

## STF client intervalisé

Le module **STF Client** accepte un besoin de staffing déjà calculé par le client et déjà distribué par intervalle. Un fichier **CSV UTF-8 ou Excel (.xlsx)** est accepté ; les colonnes attendues sont :

`date,interval_start,interval_end,required_hc`

Pour une même semaine ISO + campagne + skill, chaque nouvel import devient la version courante et l'ancienne version reste historisée.

Règle de priorité opérationnelle :

1. si un STF client courant couvre l'intervalle, `required_hc` opérationnel = STF client ;
2. sinon, le besoin calculé par Daily/Intraday reste utilisé.

Les KPI de staffing sont alors recalculés sur le besoin client : **Required HC-hours, Coverage, Shortage, Surplus, Peak STF, OT requis, FTE équivalent**. Le système mesure aussi l'écart **STF client vs besoin calculé WFM** pour détecter les différences de modèle.

Le STF client ne contient pas nécessairement le volume/AHT : dans ce cas, il ne remplace pas les données de trafic utilisées pour Erlang C. Les KPI **Service Level, ASA et Occupancy** continuent de dépendre du volume/AHT/actuals disponibles. Ainsi, on évite de fabriquer un SL/ASA à partir du seul STF.

Le Planner, le Dashboard, Daily, l'impact des pauses et Overtime consomment tous ce besoin effectif. Le fichier client devient donc une vraie source de staffing, pas seulement une pièce jointe ou une valeur d'affichage.
