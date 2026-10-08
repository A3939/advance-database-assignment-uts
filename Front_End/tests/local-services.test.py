"""Offline safety contracts for the service launcher; never connect to a database."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location("local_services", Path(__file__).parents[1] / "scripts/local-services.py")
services = importlib.util.module_from_spec(spec)
spec.loader.exec_module(services)


class LocalServicesTests(unittest.TestCase):
    def test_database_ownership_includes_volume_and_mount(self):
        cfg = {"instance_id": "owner", "volume": "owned-volume"}
        info = {"Config": {"Labels": {"arsia.imports.instance": "owner"}}, "Mounts": [{"Name": "owned-volume", "Destination": "/var/lib/postgresql/data"}]}
        volume = {"Labels": {"arsia.imports.instance": "owner"}}
        services.verify_container(cfg, info, volume)
        with self.assertRaises(services.ServiceError):
            services.verify_container(cfg, info, {"Labels": {"arsia.imports.instance": "another-owner"}})
        with self.assertRaises(services.ServiceError):
            services.verify_container(cfg, {**info, "Mounts": []}, volume)

    def test_other_workspace_on_3100_is_not_adopted(self):
        responses = ["123\n", "pcwd\nn/another/project\n", "next-server\n"]
        with patch.object(services, "command", side_effect=[SimpleNamespace(stdout=x) for x in responses]):
            with self.assertRaises(services.ServiceError):
                services.web_pid()

    def test_owned_web_is_reused(self):
        responses = ["123\n123\n", "pcwd\nn" + str(services.PROJECT) + "\n", "next-server (v16)\n"]
        with patch.object(services, "command", side_effect=[SimpleNamespace(stdout=x) for x in responses]):
            self.assertEqual(services.web_pid(), 123)

    def test_unfinished_or_queued_tasks_block_cold_worker_start(self):
        from arsia_pipeline import store
        for jobs, attempts in [([{"id": "queued"}], []), ([], [{"id": "unfinished"}]), ([], [])]:
            conn = MagicMock()
            conn.execute.side_effect = [None, SimpleNamespace(fetchall=lambda: jobs), SimpleNamespace(fetchall=lambda: attempts)]
            with patch.object(store, "connect") as connect:
                connect.return_value.__enter__.return_value = conn
                if jobs or attempts:
                    with self.assertRaises(services.ServiceError):
                        services.require_quiet_database({})
                else:
                    services.require_quiet_database({})
                queries = [c.args[0] for c in conn.execute.call_args_list]
                self.assertTrue(queries[0].endswith("READ ONLY"))
                self.assertTrue(all(q.startswith("SELECT") for q in queries[1:]))

    def test_readiness_requires_worker_and_does_not_claim_live_ai(self):
        data = {"/api/imports/health": {"http": 200, "body": {"worker": {"alive": True}}},
                "/api/data/catalog": {"http": 200, "body": {"releaseId": "release"}},
                "/api/studio/capabilities": {"http": 200, "body": {"assistant": {"available": True}}}}
        checks = {"import_executor": True, "analysis_sandbox": True, "agent_runtime": True}
        with patch.object(services, "web_pid", return_value=123), patch.object(services, "get", side_effect=data.get), patch.object(services, "runtime_checks", return_value=checks):
            self.assertTrue(services.status()["services_ready"])
            self.assertEqual(services.status()["ai_live_check"], "not performed by status")
            data["/api/imports/health"]["body"]["worker"]["alive"] = False
            self.assertFalse(services.status()["services_ready"])
            data["/api/imports/health"]["body"]["worker"]["alive"] = True
            checks["analysis_sandbox"] = False
            self.assertFalse(services.status()["services_ready"])

    def test_stop_refuses_active_studio_before_stopping_any_process(self):
        dev = MagicMock()
        with patch.object(services, "web_pid", return_value=123), patch.object(services, "runtime", return_value=(dev, {})), \
             patch.object(services, "database_ready", return_value={}), patch.object(services, "require_quiet_database"), \
             patch.object(services, "require_quiet_studio", side_effect=services.ServiceError("active")), patch.object(services.os, "kill") as kill:
            with self.assertRaises(services.ServiceError):
                services.stop()
            dev.stop_processes.assert_not_called()
            kill.assert_not_called()

    def test_start_does_not_initialize_or_replace_live_web(self):
        dev = MagicMock()
        dev.owned_pid.return_value = True
        cfg = {"agent_engine": "deterministic", "executor_image": "sha256:reviewed", "processes": {"worker": 456}}
        with patch.object(services, "web_pid", return_value=123), patch.object(services, "runtime", return_value=(dev, cfg)), \
             patch.object(services, "database_ready", return_value=cfg), patch.object(services, "runtime_checks", return_value={"ready": True}), \
             patch.object(services, "status", return_value={"services_ready": True}), patch.object(services.subprocess, "Popen") as popen:
            self.assertTrue(services.start()["services_ready"])
            popen.assert_not_called()
            dev.ensure_database.assert_not_called()
            self.assertEqual([c.args[1] for c in dev.launch.call_args_list], ["api", "worker"])


if __name__ == "__main__":
    unittest.main()
