from __future__ import annotations

import asyncio
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main
from app.models import GitHubSyncResult


class SyncEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_app_data_runs_off_the_event_loop(self) -> None:
        event_loop_thread = threading.get_ident()
        store_thread: list[int] = []

        def app_data_from_worker() -> object:
            store_thread.append(threading.get_ident())
            return object()

        with patch.object(main.store, "app_data", side_effect=app_data_from_worker):
            await main.get_app_data()

        self.assertEqual(len(store_thread), 1)
        self.assertNotEqual(store_thread[0], event_loop_thread)

    async def test_sync_does_not_block_health_endpoint(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def slow_sync(_store: object) -> GitHubSyncResult:
            started.set()
            release.wait(timeout=2)
            return GitHubSyncResult(
                syncedAt="2026-01-01T00:00:00+00:00",
                repositoriesScanned=1,
                pullRequestsImported=0,
                errors=[],
            )

        with patch.object(main, "sync_github_pull_requests", side_effect=slow_sync):
            sync_task = asyncio.create_task(main.post_github_sync())
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            self.assertEqual(await asyncio.wait_for(main.health(), timeout=0.2), {"status": "ok"})
            release.set()
            result = await sync_task

        self.assertEqual(result.repositoriesScanned, 1)
