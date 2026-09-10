"""Instance Jinja2Templates partagée par tous les routers.

Un seul point de configuration pour le dossier de templates, réutilisé
partout plutôt que d'instancier Jinja2Templates dans chaque router.
"""

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
