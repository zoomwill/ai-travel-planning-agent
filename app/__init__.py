"""Application package security defaults.

LangGraph reads its strict MessagePack flag when the library is imported. Enforce
the safe setting as soon as Python imports ``app`` so graph compilation can
derive an allowlist from the project's typed state schemas.
"""

import os

os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
