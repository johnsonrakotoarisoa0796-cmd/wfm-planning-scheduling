from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.models.campaign import Campaign
from app.models.employee import Employee
from app.models.employee import EmployeeSkill
from app.models.enums import Channel, EmployeeStatus
from app.models.market import Market
from app.models.skill import Skill
from app.services.workforce_agents_service import generate_synthetic_employees, import_real_employees


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _scope(session: Session):
    market = Market(code="UK", name="United Kingdom", language_code="en", timezone_name="Europe/London", is_active=True)
    session.add(market)
    session.commit()
    campaign = Campaign(name="Support UK", code="SUP-UK", is_active=True)
    session.add(campaign)
    session.commit()
    skill = Skill(campaign_id=campaign.id, market_id=market.id, name="Message Us", channel=Channel.CHAT, concurrency_factor=2.0, is_active=True)
    session.add(skill)
    session.commit()
    return campaign, skill


def test_generate_synthetic_employees_is_bulk_and_marked_synthetic():
    engine = _db()
    with Session(engine) as session:
        campaign, skill = _scope(session)
        employees = generate_synthetic_employees(
            session,
            campaign_id=campaign.id,
            skill_id=skill.id,
            count=140,
            hire_date=date(2026, 1, 5),
            weekly_hours_contract=40,
            timezone_name="Europe/London",
        )
        assert len(employees) == 140
        codes = [employee.employee_code for employee in employees]
        assert len(set(codes)) == 140
        assert codes[0].endswith("0001")
        assert codes[-1].endswith("0140")
        assert session.exec(select(Employee)).all()
        assert all(employee.data_source == "synthetic" for employee in employees)
        assert all(employee.status == EmployeeStatus.ACTIVE for employee in employees)
        links = session.exec(select(EmployeeSkill)).all()
        assert len(links) == 140
        assert all(link.skill_id == skill.id for link in links)


def test_import_real_employees_creates_and_updates_by_employee_code():
    engine = _db()
    with Session(engine) as session:
        campaign, skill = _scope(session)
        content = (
            "employee_code,first_name,last_name,campaign_code,skill_name,hire_date,weekly_hours_contract,timezone_name\n"
            "UKMSG001,John,Smith,SUP-UK,Message Us,2026-01-05,40,Europe/London\n"
            "UKMSG002,Sarah,Jones,SUP-UK,Message Us,2026-02-02,40,Europe/London\n"
        ).encode()
        result = import_real_employees(session, filename="agents.csv", content=content)
        assert result.imported == 2
        assert result.updated == 0
        assert result.skipped == 0
        update = (
            "employee_code,first_name,last_name,campaign_code,skill_name,hire_date,weekly_hours_contract,timezone_name\n"
            "UKMSG001,John,Smith,SUP-UK,Message Us,2026-01-05,37.5,Europe/London\n"
        ).encode()
        result = import_real_employees(session, filename="agents.csv", content=update)
        assert result.updated == 1
        employee = session.exec(select(Employee).where(Employee.employee_code == "UKMSG001")).one()
        assert employee.weekly_hours_contract == 37.5


def test_generate_synthetic_employees_recovers_stale_homonymous_skill_from_another_campaign():
    engine = _db()
    with Session(engine) as session:
        first_campaign, first_skill = _scope(session)
        second_campaign = Campaign(name="Support DE", code="SUP-DE", is_active=True)
        session.add(second_campaign)
        session.commit()
        second_skill = Skill(
            campaign_id=second_campaign.id,
            name="Message Us",
            channel=Channel.CHAT,
            concurrency_factor=2.0,
            is_active=True,
        )
        session.add(second_skill)
        session.commit()

        employees = generate_synthetic_employees(
            session,
            campaign_id=second_campaign.id,
            skill_id=first_skill.id,
            count=1,
            hire_date=date(2026, 1, 5),
            weekly_hours_contract=40,
            timezone_name="Europe/Berlin",
        )

        assert len(employees) == 1
        link = session.exec(select(EmployeeSkill).where(EmployeeSkill.employee_id == employees[0].id)).one()
        assert link.skill_id == second_skill.id


def test_generate_synthetic_employees_continues_existing_code_sequence_without_per_agent_queries():
    engine = _db()
    with Session(engine) as session:
        campaign, skill = _scope(session)
        session.add(Employee(
            employee_code="SYN-123-0042",
            first_name="Existing",
            last_name="Agent",
            campaign_id=campaign.id,
            hire_date=date(2026, 1, 1),
            status=EmployeeStatus.ACTIVE,
            weekly_hours_contract=40,
            timezone_name="Europe/London",
            data_source="synthetic",
        ))
        session.commit()

        employees = generate_synthetic_employees(
            session,
            campaign_id=campaign.id,
            skill_id=skill.id,
            count=2,
            hire_date=date(2026, 1, 5),
            weekly_hours_contract=40,
            timezone_name="Europe/London",
        )
        assert [employee.employee_code for employee in employees] == ["SYN-123-0043", "SYN-123-0044"]
