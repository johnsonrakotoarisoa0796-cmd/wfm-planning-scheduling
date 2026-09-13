"""Crée des données de référence minimales (Campaign + Skill + employés +
catégories Shrinkage) pour un usage LOCAL avec accès direct à DATABASE_URL.

Délègue aux mêmes fonctions que le bootstrap cloud (app/main.py) plutôt
que de dupliquer la logique — une seule source de vérité pour les données
de démo, qu'on soit en local ou sur Render sans accès shell (voir
BOOTSTRAP_DEMO_DATA dans le README).

Usage :
    python -m app.scripts.seed_demo_data
"""

import os

os.environ.setdefault("BOOTSTRAP_DEMO_DATA", "true")

from app.main import bootstrap_demo_data_if_configured, bootstrap_shrinkage_categories  # noqa: E402


def main() -> None:
    bootstrap_demo_data_if_configured()
    bootstrap_shrinkage_categories()


if __name__ == "__main__":
    main()
