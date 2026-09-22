# WFM AI Copilot

## Objectif

Le Copilot IA ajoute une couche d'analyse au-dessus du moteur WFM déterministe.

Il couvre quatre modes :

- Copilot général : questions transverses sur le périmètre sélectionné.
- Report : synthèse KPI, risques et actions.
- Planning : analyse forecast, capacité et staffing, avec scénarios.
- Scheduling : recommandations de couverture, shifts, pauses et contraintes.

## Sécurité de conception

L'IA ne modifie jamais directement la base.

Les changements réels restent exécutés par les moteurs existants :
forecast, capacity planning, planner, auto scheduler et compliance.

Le prompt impose l'utilisation des seules données du snapshot WFM transmis à l'IA et interdit l'invention de KPI.

## Configuration

Ajouter dans Render / environnement :

AI_API_KEY=...
AI_MODEL=...
AI_API_BASE_URL=...
AI_PROVIDER=openai-compatible

`AI_API_BASE_URL` doit exposer un endpoint compatible `/chat/completions`.

Sans clé ou modèle, la page reste disponible mais indique que l'IA n'est pas configurée.

## Données transmises

Le snapshot contient uniquement les agrégats nécessaires :

- période et périmètre campagne/skill
- volume forecast et actual
- AHT, Service Level, ASA, Occupancy, abandon si disponibles
- heures Required / Scheduled / Actual et staffing gap
- effectif actif et planning
- absences
- cohortes Recruitment / Training / Nesting / Production

Aucun secret de l'application n'est envoyé au provider.
