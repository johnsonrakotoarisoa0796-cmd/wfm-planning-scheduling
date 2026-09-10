"""Crée le premier compte administrateur.

Aucune inscription libre en V1 (§49 — surface d'attaque réduite) : ce script
est le seul moyen de créer un utilisateur tant que la page Settings >
Utilisateurs n'existe pas. Prérequis : les migrations Alembic doivent déjà
avoir été appliquées (`alembic upgrade head`).

Usage :
    python -m app.scripts.create_admin
"""

import getpass
import sys

import qrcode
from sqlmodel import Session, select

from app.core.database import engine
from app.core.security import generate_totp_secret, hash_password, totp_provisioning_uri
from app.models.enums import UserRole
from app.models.user import User


def main() -> None:
    print("=== Création du premier compte administrateur — WFM Planning & Scheduling ===\n")

    email = input("Email : ").strip()
    if not email or "@" not in email:
        print("Email invalide.")
        sys.exit(1)

    password = getpass.getpass("Mot de passe : ")
    password_confirm = getpass.getpass("Confirmer le mot de passe : ")
    if password != password_confirm:
        print("Les mots de passe ne correspondent pas.")
        sys.exit(1)
    if len(password) < 8:
        print("Le mot de passe doit faire au moins 8 caractères.")
        sys.exit(1)

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            print(f"Un utilisateur existe déjà avec l'email {email}.")
            sys.exit(1)

        totp_secret = generate_totp_secret()
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
            totp_secret=totp_secret,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    uri = totp_provisioning_uri(totp_secret, email)

    print(f"\nCompte administrateur créé (id={user.id}).")
    print("\n--- Configuration de l'authentification à deux facteurs (TOTP) ---")
    print("Scannez ce QR code avec Google Authenticator, Authy, ou équivalent :\n")

    qr = qrcode.QRCode(border=1)
    qr.add_data(uri)
    qr.make()
    qr.print_ascii()

    print(f"\nOu saisissez la clé manuellement : {totp_secret}")
    print(f"URI complète (debug) : {uri}\n")
    print("Connectez-vous ensuite sur /login avec cet email et ce mot de passe.")


if __name__ == "__main__":
    main()
