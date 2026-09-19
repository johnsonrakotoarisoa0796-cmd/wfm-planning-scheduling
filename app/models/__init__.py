"""Import centralise de tous les modeles SQLModel.

Ce fichier garantit que chaque modele est enregistre dans SQLModel.metadata
avant qu'Alembic ne genere une migration (--autogenerate) ou qu'un test
appelle SQLModel.metadata.create_all(). Toute nouvelle table doit etre
ajoutee ici.
"""

from app.models.agent_request import AgentRequest
from app.models.campaign import Campaign
from app.models.market import Market
from app.models.weekly_parameters import WeeklyWFMParameter
from app.models.recruitment import RecruitmentPlan, RecruitmentRampWeek
from app.models.client_stf import ClientSTFInterval, ClientSTFPlan
from app.models.capacity import CapacityPlan
from app.models.campaign_workforce import CampaignWorkforcePlan
from app.models.config_parameter import ConfigParameter
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.forecast import ForecastVersion, LTFForecast, STFForecast
from app.models.intraday import ActualPerformanceRaw, DailyForecast, IntervalForecast
from app.models.overtime import OvertimePlan
from app.models.schedule import ScheduleEntry
from app.models.shift import Shift
from app.models.shrinkage import ShrinkageCategory, ShrinkageRecord
from app.models.skill import Skill
from app.models.sla import SLAProfile
from app.models.user import User

__all__ = [
    "AgentRequest",
    "Campaign",
    "Market",
    "ClientSTFInterval",
    "ClientSTFPlan",
    "CapacityPlan",
    "CampaignWorkforcePlan",
    "ConfigParameter",
    "Employee",
    "EmployeeAbsence",
    "EmployeeSkill",
    "ForecastVersion",
    "LTFForecast",
    "STFForecast",
    "ActualPerformanceRaw",
    "DailyForecast",
    "IntervalForecast",
    "OvertimePlan",
    "ScheduleEntry",
    "Shift",
    "ShrinkageCategory",
    "ShrinkageRecord",
    "Skill",
    "WeeklyWFMParameter",
    "RecruitmentPlan",
    "RecruitmentRampWeek",
    "SLAProfile",
    "User",
]
