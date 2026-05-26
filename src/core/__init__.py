"""
Core modules for AI-SAST security scanner
"""

from .scanner import SecurityScanner
from .report import HTMLReportGenerator
from .config import PROJECT_ID, LOCATION

# Vertex AI client is optional: its Google Cloud deps are only needed when
# AI_SAST_LLM=vertex. Azure/Bedrock/Ollama-only installs can skip them.
try:
    from .vertex import VertexAIClient
except ImportError:
    VertexAIClient = None

# Optional integrations
try:
    from ..integrations.jira import JiraClient
except ImportError:
    JiraClient = None

try:
    from ..integrations.databricks import DatabricksClient
except ImportError:
    DatabricksClient = None

try:
    from ..integrations.vector import VectorClient, log_security_event
except ImportError:
    VectorClient = None
    log_security_event = None

try:
    from ..integrations.notifications import WebhookClient as NotificationClient
except ImportError:
    NotificationClient = None

__all__ = [
    'SecurityScanner',
    'VertexAIClient', 
    'HTMLReportGenerator',
    'PROJECT_ID',
    'LOCATION',
    'JiraClient',
    'DatabricksClient',
    'VectorClient',
    'log_security_event',
    'NotificationClient'
]

