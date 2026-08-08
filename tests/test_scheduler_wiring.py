"""Regression tests for how the nightly job is wired.

The original failure mode here was not a crash but a name collision:
``app/core/scheduler.py`` defined its own log-only ``run_abc_analysis`` stub,
which shadowed the real implementation in ``app.modules.analytics``. The
scheduler registered the stub, so every night the logs cheerfully reported "ABC
Analysis complete!" while nothing was computed and nothing was stored.

Wiring bugs like that produce no error and no failing test unless something
asserts on the wiring itself — which is what this file does.
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.core import scheduler
from app.modules.analytics import abc_analysis, forecast


def test_scheduler_calls_the_real_abc_implementation():
    """Not a log-only stub of the same name."""
    assert scheduler.run_abc_analysis is abc_analysis.run_abc_analysis


def test_scheduler_calls_the_real_forecast_implementation():
    assert scheduler.run_demand_forecast is forecast.run_demand_forecast


def test_unimplemented_archival_job_refuses_to_pretend_it_worked():
    """It previously logged "Archival complete. Database performance optimal."
    without archiving anything, which is worse than not existing."""
    with pytest.raises(NotImplementedError):
        scheduler.archive_cold_data()


def test_nightly_analytics_runs_etl_before_reading_the_lake(monkeypatch):
    """Order matters: both analytics read the Parquet file the ETL writes."""
    calls = []

    monkeypatch.setattr(
        scheduler, "run_nightly_etl", lambda *a, **k: calls.append("etl")
    )
    monkeypatch.setattr(
        scheduler,
        "run_abc_analysis",
        lambda *a, **k: (calls.append("abc"), pd.DataFrame())[1],
    )
    monkeypatch.setattr(
        scheduler,
        "run_demand_forecast",
        lambda *a, **k: (calls.append("forecast"), pd.DataFrame())[1],
    )
    monkeypatch.setattr(scheduler, "persist_abc_classes", lambda db, df: 0)
    monkeypatch.setattr(scheduler, "persist_reorder_recommendations", lambda db, df: 0)
    monkeypatch.setattr(scheduler, "SessionLocal", MagicMock())

    scheduler.run_nightly_analytics()

    assert calls == ["etl", "abc", "forecast"]


def test_nightly_analytics_commits_its_results(monkeypatch):
    """The whole point of the job is that the results are persisted."""
    session = MagicMock()

    monkeypatch.setattr(scheduler, "run_nightly_etl", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "run_abc_analysis", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(
        scheduler, "run_demand_forecast", lambda *a, **k: pd.DataFrame()
    )
    monkeypatch.setattr(scheduler, "persist_abc_classes", lambda db, df: 7)
    monkeypatch.setattr(scheduler, "persist_reorder_recommendations", lambda db, df: 3)
    # Recording and scoring forecasts runs in the same transaction as the rest.
    # Stubbed here too: this test is about the commit boundary, and a real
    # scoring pass against a MagicMock session would fail for reasons that have
    # nothing to do with what is being asserted.
    monkeypatch.setattr(scheduler, "persist_forecast_runs", lambda db, df, **kwargs: 5)
    monkeypatch.setattr(scheduler, "score_due_forecasts", lambda db: 2)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: session)

    summary = scheduler.run_nightly_analytics()

    assert summary == {
        "products_classified": 7,
        "recommendations_created": 3,
        "forecasts_recorded": 5,
        "forecasts_scored": 2,
    }
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_nightly_analytics_rolls_back_and_reraises_on_failure(monkeypatch):
    """A half-written analytics run must not be committed, and the scheduler must
    learn about the failure rather than recording a success."""
    session = MagicMock()

    monkeypatch.setattr(scheduler, "run_nightly_etl", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "run_abc_analysis", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(
        scheduler, "run_demand_forecast", lambda *a, **k: pd.DataFrame()
    )

    def explode(db, df):
        raise RuntimeError("persistence blew up")

    monkeypatch.setattr(scheduler, "persist_abc_classes", explode)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: session)

    with pytest.raises(RuntimeError, match="persistence blew up"):
        scheduler.run_nightly_analytics()

    session.rollback.assert_called_once()
    session.commit.assert_not_called()
    session.close.assert_called_once()


def test_etl_failure_aborts_the_run(monkeypatch):
    """If the lake was not refreshed, the analytics must not run on stale data."""

    def explode(*_a, **_k):
        raise RuntimeError("etl failed")

    monkeypatch.setattr(scheduler, "run_nightly_etl", explode)
    monkeypatch.setattr(
        scheduler,
        "run_abc_analysis",
        lambda *a, **k: pytest.fail("analytics ran despite a failed ETL"),
    )

    with pytest.raises(RuntimeError, match="etl failed"):
        scheduler.run_nightly_analytics()
