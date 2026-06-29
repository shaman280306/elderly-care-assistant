import os
import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ElderlyCareMCP")

# In-memory mock database for elderly care management
medication_schedules = {
    "patient_123": [
        {"med_name": "Lisinopril", "dosage": "10mg", "time_slots": ["08:00 AM"], "special_instructions": "Take on an empty stomach."},
        {"med_name": "Metformin", "dosage": "500mg", "time_slots": ["08:00 AM", "06:00 PM"], "special_instructions": "Take with meals."}
    ]
}

doctor_visits = {
    "patient_123": [
        {"doctor_name": "Dr. Sarah Jenkins", "specialty": "Cardiology", "date_time": "2026-07-15 10:00 AM", "clinic_name": "Metro Heart Center", "preparation": "Fasting required 12 hours before."}
    ]
}

@mcp.tool()
def get_medication_schedule(patient_id: str) -> str:
    """Retrieve the medication schedule for a given patient.
    
    Args:
        patient_id: The ID of the patient (e.g. 'patient_123').
    """
    schedules = medication_schedules.get(patient_id, [])
    if not schedules:
        return f"No medication schedule found for patient ID '{patient_id}'."
    
    lines = [f"Medication Schedule for {patient_id}:"]
    for idx, med in enumerate(schedules, 1):
        times = ", ".join(med["time_slots"])
        lines.append(f"{idx}. {med['med_name']} ({med['dosage']}) - Times: {times} | Note: {med['special_instructions']}")
    return "\n".join(lines)

@mcp.tool()
def add_medication(patient_id: str, med_name: str, dosage: str, time_slots: list[str], special_instructions: str = "") -> str:
    """Add a new medication to the patient's schedule.
    
    Args:
        patient_id: The ID of the patient (e.g. 'patient_123').
        med_name: The name of the medication.
        dosage: The dosage (e.g. '10mg', '1 tablet').
        time_slots: List of times to take the medication (e.g. ['08:00 AM', '08:00 PM']).
        special_instructions: Any special instructions.
    """
    if patient_id not in medication_schedules:
        medication_schedules[patient_id] = []
    
    new_med = {
        "med_name": med_name,
        "dosage": dosage,
        "time_slots": time_slots,
        "special_instructions": special_instructions
    }
    medication_schedules[patient_id].append(new_med)
    return f"Successfully added {med_name} to the schedule for patient '{patient_id}'."

@mcp.tool()
def get_upcoming_doctor_visits(patient_id: str) -> str:
    """Retrieve upcoming doctor visits for a given patient.
    
    Args:
        patient_id: The ID of the patient (e.g. 'patient_123').
    """
    visits = doctor_visits.get(patient_id, [])
    if not visits:
        return f"No upcoming doctor visits found for patient ID '{patient_id}'."
    
    lines = [f"Upcoming Doctor Visits for {patient_id}:"]
    for idx, visit in enumerate(visits, 1):
        lines.append(f"{idx}. {visit['doctor_name']} ({visit['specialty']}) at {visit['date_time']} | Clinic: {visit['clinic_name']} | Prep: {visit['preparation']}")
    return "\n".join(lines)

@mcp.tool()
def schedule_doctor_visit(patient_id: str, doctor_name: str, specialty: str, date_time: str, clinic_name: str, preparation: str = "") -> str:
    """Schedule a new doctor visit for a patient.
    
    Args:
        patient_id: The ID of the patient (e.g. 'patient_123').
        doctor_name: The name of the doctor (e.g. 'Dr. Smith').
        specialty: The medical specialty (e.g. 'Cardiology', 'General Practice').
        date_time: The date and time of the appointment (e.g. '2026-07-20 02:00 PM').
        clinic_name: The name of the clinic or hospital.
        preparation: Any preparations required (e.g. 'Bring current meds', 'No food after midnight').
    """
    if patient_id not in doctor_visits:
        doctor_visits[patient_id] = []
    
    new_visit = {
        "doctor_name": doctor_name,
        "specialty": specialty,
        "date_time": date_time,
        "clinic_name": clinic_name,
        "preparation": preparation
    }
    doctor_visits[patient_id].append(new_visit)
    return f"Successfully scheduled visit with {doctor_name} on {date_time} for patient '{patient_id}'."

if __name__ == "__main__":
    mcp.run()
