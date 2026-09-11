"""Crée des données de référence minimales (Campaign + Skill).

Il n'existe pas encore de page d'administration Campaigns/Skills — à
ajouter au module Settings quand il sera construit. En attendant, ce script
débloque les tests manuels des modules LTF/STF/Daily.

Usage :
    python -m app.scripts.seed_demo_data
"""

from sqlmodel import Session, select

from app.core.database import engine
from app.models.campaign import Campaign
from app.models.enums import Channel
from app.models.skill import Skill


def main() -> None:
    with Session(engine) as session:
        existing = session.exec(select(Campaign)).first()
        if existing:
            print("Des campagnes existent déjà en base — rien à faire.")
            return

        campaign = Campaign(name="Support Client FR", code="SUP-FR")
        session.add(campaign)
        session.commit()
        session.refresh(campaign)

        skill = Skill(campaign_id=campaign.id, name="Voix Niveau 1", channel=Channel.VOICE)
        session.add(skill)
        session.commit()
        session.refresh(skill)

        print(f"Campagne créée : {campaign.name} (id={campaign.id}, code={campaign.code})")
        print(f"Skill créée : {skill.name} (id={skill.id}, channel={skill.channel.value})")


if __name__ == "__main__":
    main()
