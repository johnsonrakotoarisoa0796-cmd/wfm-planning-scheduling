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

Le mode gratuit reste disponible sans clé API. Une clé et un modèle sont nécessaires uniquement pour le moteur « IA avancée ».

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


## Mode gratuit

Le moteur **Gratuit · moteur WFM local** est le mode par défaut.

Il ne contacte aucun provider externe. Il calcule localement :

- écart forecast vs actual et son pourcentage
- heures Required / Scheduled / Actual
- sous-staffing / surstaffing
- alertes Service Level et Occupancy
- impact des absences
- situation Training / Nesting / Production
- actions WFM déterministes à examiner

Ce mode ne génère pas de texte libre avec un LLM : il produit un report opérationnel basé sur les règles et KPI calculés par l'application.

## Mode IA avancée

Le moteur **IA avancée** n'est proposé que lorsqu'un provider est configuré.

Il sert à reformuler et développer les analyses, répondre aux demandes ouvertes et produire des scénarios textuels plus riches.

Ainsi, l'application peut fonctionner sans coût d'API IA au quotidien et n'utiliser l'IA externe que lorsque l'utilisateur le décide.
