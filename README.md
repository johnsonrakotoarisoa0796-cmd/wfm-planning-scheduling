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
