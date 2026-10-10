"""Background jobs: the scripted scenario baseline and conversation clean-up."""

from __future__ import annotations

from procrastinate import Blueprint

from reluai_core.cpu_lease import LeaseUnavailableError, cpu_lease
from reluai_core.jobs import QUEUE_DEFAULT
from reluai_core.logging import get_logger
from reluai_core.runtime import get_runtime
from reluai_support.settings import get_support_settings

blueprint = Blueprint()
log = get_logger(__name__)


@blueprint.periodic(cron="53 3 * * *", periodic_id="support-daily")
@blueprint.task(name="support_daily", queue=QUEUE_DEFAULT)
def support_daily(timestamp: int) -> None:
    """Delete conversations past their 24-hour life; re-run the scripted baseline.

    Model evaluations are run by hand (``reluai-support evaluate --provider groq``) because
    a full suite would use most of a day's free-tier tokens.
    """
    from reluai_support import service
    from reluai_support.agent import scripted_chain
    from reluai_support.evaluation import run_evaluation

    rt = get_runtime()
    settings = get_support_settings()
    removed = service.purge(rt.db, settings)
    try:
        with cpu_lease(
            rt.db.engine,
            holder="support-evaluation",
            wait_seconds=rt.settings.cpu_lease_wait_seconds,
        ):
            summary = run_evaluation(
                lambda cf: service.runtime(rt.db, settings, cf, None),
                scripted_chain,
                label="scripted",
            )
            service.record_evaluation(rt.db, summary)
    except FileNotFoundError:
        log.warning("support.evaluation_skipped", reason="order snapshot not built")
    except LeaseUnavailableError:
        log.warning("support.evaluation_skipped", reason="cpu lease busy")
    log.info("support.daily_done", removed=removed, timestamp=timestamp)
