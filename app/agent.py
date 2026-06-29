# ruff: noqa
import os
import re
import json
import time
import logging
from typing import Any
from pydantic import BaseModel, Field

from google.adk.agents import Agent, Context
from google.adk.models import Gemini
from google.adk.workflow import node, START, Edge, Workflow
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import McpToolset
from google.adk.apps import App
from mcp import StdioServerParameters
from app.config import config

# Clear local GCP environment settings (use Gemini API key via .env only)
if "GOOGLE_CLOUD_PROJECT" in os.environ:
    del os.environ["GOOGLE_CLOUD_PROJECT"]
if "GOOGLE_CLOUD_LOCATION" in os.environ:
    del os.environ["GOOGLE_CLOUD_LOCATION"]
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("elderly_care_agent")

def extract_text(node_input: Any) -> str:
    if not node_input:
        return ""
    if isinstance(node_input, str):
        return node_input
    if hasattr(node_input, "parts") and node_input.parts:
        parts_text = []
        for part in node_input.parts:
            if hasattr(part, "text") and part.text:
                parts_text.append(part.text)
        return "\n".join(parts_text)
    if isinstance(node_input, dict):
        if "parts" in node_input:
            parts = node_input["parts"]
            if isinstance(parts, list):
                return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)
        if "output" in node_input:
            return str(node_input["output"])
    return str(node_input)

# ---------------------------------------------------------------------------
# MCP Toolset connection parameters
# ---------------------------------------------------------------------------

mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "app.mcp_server"]
    )
)

# ---------------------------------------------------------------------------
# Specialized Specialist Sub-Agents
# ---------------------------------------------------------------------------

medication_agent = Agent(
    name="medication_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are a specialized Medication Scheduler Agent for elderly care.\n"
        "Analyze medical queries or prescription notes and provide detailed medication schedules.\n"
        "Use your MCP tools to get or add medication schedules when requested.\n"
        "Include specific times for taking the medications, dosage info, and special instructions (e.g. take with food).\n"
        "Be clear, compassionate, and precise."
    ),
    tools=[mcp_toolset]
)

doctor_agent = Agent(
    name="doctor_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are a specialized Doctor Coordinator Agent for elderly care.\n"
        "Analyze schedule coordinates, log doctor visits, and prepare patient clinic logs.\n"
        "Use your MCP tools to get upcoming doctor visits or schedule a doctor visit when requested.\n"
        "Include appointment details (date, time, doctor name, clinic) and preparation notes.\n"
        "Be precise, patient, and highly organized."
    ),
    tools=[mcp_toolset]
)

# ---------------------------------------------------------------------------
# Lead Coordinator / Orchestrator
# ---------------------------------------------------------------------------

orchestrator = Agent(
    name="orchestrator",
    model=Gemini(model=config.model),
    instruction=(
        "You are the main coordinator for an Elderly Care Assistant.\n"
        "Your job is to route patient requests to either the Medication Scheduler (medication_agent) or the Doctor Coordinator (doctor_agent), or handle general inquiries yourself.\n"
        "Use the specialized tools:\n"
        "- medication_agent for medication, prescription, or dosage questions.\n"
        "- doctor_agent for coordinating doctor appointments, clinic visits, or preparation lists.\n"
        "If you delegate to a sub-agent, present their final answer clearly.\n"
        "Always end your responses with a caring closing statement."
    ),
    tools=[
        AgentTool(medication_agent),
        AgentTool(doctor_agent)
    ]
)

# ---------------------------------------------------------------------------
# Workflow State Schema
# ---------------------------------------------------------------------------

class CareState(BaseModel):
    raw_query: str = ""
    sanitized_query: str = ""
    security_alert_reason: str = ""
    requires_disclaimer: bool = False
    approved: bool = False
    audit_logs: list[str] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Workflow Nodes
# ---------------------------------------------------------------------------

@node(name="security_checkpoint")
async def security_checkpoint(ctx: Context, node_input: Any):
    query = extract_text(node_input)
    
    # Initialize state
    ctx.state["raw_query"] = query
    ctx.state["approved"] = False
    
    # 1. Prompt Injection Keyword Detection
    injection_keywords = ["override instructions", "ignore previous instructions", "system prompt", "forget instructions"]
    has_injection = any(kw in query.lower() for kw in injection_keywords)
    
    # 2. PII Scrubbing
    scrubbed_query = query
    phone_pattern = r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
    
    scrubbed_query = re.sub(phone_pattern, "[PHONE REDACTED]", scrubbed_query)
    scrubbed_query = re.sub(email_pattern, "[EMAIL REDACTED]", scrubbed_query)
    scrubbed_query = re.sub(ssn_pattern, "[SSN REDACTED]", scrubbed_query)
    
    ctx.state["sanitized_query"] = scrubbed_query
    
    # 3. Domain-Specific Rule: medical disclaimer required?
    medical_terms = ["dosage", "dose", "medication", "pill", "prescription"]
    requires_disclaimer = any(term in scrubbed_query.lower() for term in medical_terms)
    ctx.state["requires_disclaimer"] = requires_disclaimer
    
    # 4. JSON Audit Log
    severity = "INFO"
    reason = "Safe query received."
    
    if has_injection:
        severity = "CRITICAL"
        reason = "Prompt injection attempt detected!"
    elif requires_disclaimer:
        severity = "WARNING"
        reason = "Medical instruction query detected; medical disclaimer will be applied."
        
    audit_log = {
        "timestamp": time.time(),
        "severity": severity,
        "reason": reason,
        "original_query_length": len(query),
        "pii_detected": scrubbed_query != query,
    }
    
    audit_list = list(ctx.state.get("audit_logs", []))
    audit_list.append(json.dumps(audit_log))
    ctx.state["audit_logs"] = audit_list
    
    logger.info(f"[{severity}] SECURITY AUDIT: {json.dumps(audit_log)}")
    
    if has_injection:
        ctx.state["security_alert_reason"] = "Query blocked: Prompt injection attempt detected."
        return Event(
            output="Blocked",
            route="SECURITY_EVENT",
            state={"security_alert_reason": "Query blocked: Prompt injection attempt detected."}
        )
        
    return Event(
        output=scrubbed_query,
        route="ORCHESTRATE",
        state={"sanitized_query": scrubbed_query}
    )

@node(name="security_error_node")
async def security_error_node(ctx: Context, node_input: Any):
    return f"Security Alert: {ctx.state.get('security_alert_reason', 'Access denied due to security policy violations.')}"

@node(name="human_review", rerun_on_resume=True)
async def human_review(ctx: Context, node_input: Any):
    text_input = extract_text(node_input)
    interrupt_id = "caregiver_approval"
    
    # Check if we already received the input from the resume step
    if interrupt_id not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id=interrupt_id,
            message=f"CARE REVIEW REQUIRED: Please check the proposed response for the senior citizen:\n\n{text_input}\n\nDo you approve sending this? (yes/no)",
            response_schema=str
        )
        return
    
    # On Resume
    response = ctx.resume_inputs[interrupt_id]
    if str(response).lower() in ("yes", "y", "approve", "approved"):
        ctx.state["approved"] = True
        disclaimer = ""
        if ctx.state.get("requires_disclaimer", False):
            disclaimer = "\n\n*Disclaimer: Please consult with your physician before making any changes to your medication schedule.*"
        yield f"{text_input}{disclaimer}"
    else:
        ctx.state["approved"] = False
        yield "The proposed response was rejected by the caregiver. Please refine your query."

@node(name="final_output_node")
async def final_output_node(ctx: Context, node_input: Any):
    return extract_text(node_input)

# ---------------------------------------------------------------------------
# Workflow Graph
# ---------------------------------------------------------------------------

workflow = Workflow(
    name="elderly_care_workflow",
    state_schema=CareState,
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=orchestrator, route="ORCHESTRATE"),
        Edge(from_node=security_checkpoint, to_node=security_error_node, route="SECURITY_EVENT"),
        Edge(from_node=orchestrator, to_node=human_review),
        Edge(from_node=human_review, to_node=final_output_node),
        Edge(from_node=security_error_node, to_node=final_output_node),
    ]
)

# ---------------------------------------------------------------------------
# App Definition
# ---------------------------------------------------------------------------

app = App(
    root_agent=workflow,
    name="app"
)
