"""Every module that owns tables, imported once so ``Base.metadata`` is complete.

Used by the Alembic environment and by the test that checks migrations against models.
"""

from __future__ import annotations

import reluai_api.contact  # noqa: F401 - registers platform.contact_message
import reluai_core.ratelimit  # noqa: F401 - registers platform.rate_counter
import reluai_csv.models  # noqa: F401 - registers csv.*
import reluai_docs.models  # noqa: F401 - registers docs.*
import reluai_inference.ledger  # noqa: F401 - registers platform.llm_usage
import reluai_pipeline.models  # noqa: F401 - registers pipeline.* and retail.*
import reluai_retrieval.models  # noqa: F401 - registers retrieval.*
import reluai_support.models  # noqa: F401 - registers support.*

SCHEMAS = {"platform", "pipeline", "retail", "csv", "retrieval", "support", "docs"}
