"""Excluded downloads fail through existing queue/error contracts before work."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.download_service import DownloadService
from core import distribution


@pytest.fixture
def service():
    app = SimpleNamespace(download_events=Queue(), log=Mock())
    return DownloadService(app)


@pytest.mark.parametrize("method", ["enqueue_from_form", "enqueue_caption_only_from_form"])
@pytest.mark.parametrize("failure", [distribution.StoreFeatureUnavailable("Excluded"),
                                    distribution.StoreBuildError("Unreadable policy")])
def test_excluded_forms_return_without_reading_or_starting_form_work(service, monkeypatch, method, failure):
    policy = Mock(side_effect=failure)
    monkeypatch.setattr(distribution, "require_feature", policy)
    getattr(service, method)()
    policy.assert_called_once_with("media_download")
    service.app.log.assert_called_once_with(str(failure))
    assert service.app.download_events.empty()


@pytest.mark.parametrize("failure", [distribution.StoreFeatureUnavailable("Excluded"),
                                    distribution.StoreBuildError("Unreadable policy")])
def test_queued_download_reports_error_before_offline_or_tool_checks(service, monkeypatch, failure):
    monkeypatch.setattr(distribution, "require_feature", Mock(side_effect=failure))
    offline = Mock(side_effect=AssertionError("No worker preparation before distribution guard"))
    monkeypatch.setattr(service, "_refused_offline", offline)
    task = object()
    service._run_task(task)
    assert service.app.download_events.get_nowait() == ("error", task, str(failure))
    offline.assert_not_called()


def test_retained_download_uses_the_existing_worker_path(service, monkeypatch):
    policy = Mock(return_value=None)
    monkeypatch.setattr(distribution, "require_feature", policy)
    offline = Mock(return_value=True)
    monkeypatch.setattr(service, "_refused_offline", offline)
    task = object()
    service._run_task(task)
    policy.assert_called_once_with("media_download")
    offline.assert_called_once_with(task)
    assert service.app.download_events.empty()


@pytest.mark.parametrize("retry_during_policy_read", [False, True])
def test_old_policy_refusal_cannot_fail_a_retried_download(service, monkeypatch, retry_during_policy_read):
    task = SimpleNamespace(_run_generation=1, status="running")
    service.app.download_current = task
    finish = Mock()
    next_task = Mock()
    monkeypatch.setattr(service, "_finish_history", finish)
    monkeypatch.setattr(service, "process_queue", next_task)

    def fail_policy(_feature):
        if retry_during_policy_read:
            task._run_generation = 2
        raise distribution.StoreBuildError("Temporary policy read failure")

    monkeypatch.setattr(distribution, "require_feature", fail_policy)
    service._run_task(task)
    event = service.app.download_events.get_nowait()
    task._run_generation = 2
    service._dispatch_event(service.app, *event, generation=getattr(event, "generation", None))
    assert task.status == "running"
    assert service.app.download_current is task
    finish.assert_not_called()
    next_task.assert_not_called()
    service.app.log.assert_not_called()


def test_current_policy_refusal_finishes_the_failed_queue_row(service, monkeypatch):
    task = SimpleNamespace(status="running", paused=False, cancelled=False)
    service.app.download_current = task
    monkeypatch.setattr(distribution, "require_feature", Mock(side_effect=distribution.StoreFeatureUnavailable("Excluded")))
    finish = Mock()
    next_task = Mock()
    monkeypatch.setattr(service, "_finish_history", finish)
    monkeypatch.setattr(service, "process_queue", next_task)
    service._run_task(task)
    event = service.app.download_events.get_nowait()
    service._dispatch_event(service.app, *event, generation=getattr(event, "generation", None))
    assert task.status == "error"
    assert service.app.download_current is None
    finish.assert_called_once_with(task, "error", [], error="Excluded")
    next_task.assert_called_once_with()
