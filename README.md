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
   health check (`/health`).

## Historique d'implémentation

Voir `WFM_ARCHITECTURE_PLAN.md` section 11 pour le détail des 16 commits
prévus, du squelette initial jusqu'au durcissement de production.
