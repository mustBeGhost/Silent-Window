"""The five agreed roles and server-enforced permissions."""
from typing import Literal

Role = Literal["admin", "doctor", "nurse", "coordinator", "researcher"]
ROLE_LABELS = {"admin": "Administrator", "doctor": "Doctor", "nurse": "Nurse",
               "coordinator": "ICU Coordinator / Head Nurse", "researcher": "Researcher / Reviewer"}
PATIENT_ROLES = {"admin", "doctor", "nurse", "coordinator"}
UNIT_ROLES = {"admin", "coordinator"}
EVENT_ROLES = {"acknowledge": {"doctor", "nurse", "coordinator"}, "review": {"doctor"},
               "observation": {"nurse"}, "handover": {"coordinator"}}


def capabilities(role):
    return {"view_patients": role in PATIENT_ROLES, "view_unit": role in UNIT_ROLES,
            "manage_accounts": role == "admin", "assign_patients": role in UNIT_ROLES,
            "prepare_index": role in UNIT_ROLES,
            "event_types": [event for event, roles in EVENT_ROLES.items() if role in roles]}
