"""Launch-boundary checks: never restart existing services or emulator instances."""
import argparse
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts.ops import root_launcher as launcher


class LaunchTests(unittest.TestCase):
    def test_backend_reuses_running_supervisor(self):
        args = argparse.Namespace(check=False, status=False)
        with patch.object(launcher, "require", side_effect=lambda path: path), \
             patch.object(launcher, "supervisor_running", return_value=True), \
             patch.object(launcher, "stack_status", return_value=True), \
             patch.object(launcher.subprocess, "Popen") as start:
            self.assertEqual(launcher.backend(args), 0)
            start.assert_not_called()

    def test_backend_does_not_report_unhealthy_stack_as_success(self):
        with patch.object(launcher, "require", side_effect=lambda path: path), \
             patch.object(launcher, "supervisor_running", return_value=True), \
             patch.object(launcher, "stack_status", return_value=False), \
             patch.object(launcher.subprocess, "Popen") as start:
            self.assertEqual(launcher.main(["backend"]), 1)
            start.assert_not_called()

    def test_missing_dependency_fails_before_start(self):
        with patch.object(launcher, "require", side_effect=RuntimeError("missing dependency")), \
             patch.object(launcher.subprocess, "Popen") as start:
            self.assertEqual(launcher.main(["backend", "--check"]), 1)
            start.assert_not_called()

    def test_status_never_starts_services(self):
        with patch.object(launcher, "stack_status", return_value=False), \
             patch.object(launcher.subprocess, "Popen") as start:
            self.assertEqual(launcher.main(["backend", "--status"]), 1)
            start.assert_not_called()

    def test_emulator_reuses_matching_avd_only(self):
        responses = ["List of devices attached\nemulator-5554\tdevice\nemulator-5556\tdevice\n",
                     "Another_AVD\nOK\n", "Medium_Phone_API_36.1\nOK\n"]
        with patch.object(launcher, "capture", side_effect=responses):
            self.assertEqual(launcher.running_avd(Path("adb.exe"), "Medium_Phone_API_36.1"),
                             "emulator-5556")

    def test_offline_emulator_prevents_duplicate_launch(self):
        with patch.object(launcher, "capture", return_value="List of devices attached\nemulator-5554\toffline\n"):
            with self.assertRaises(RuntimeError):
                launcher.running_avd(Path("adb.exe"), "Medium_Phone_API_36.1")

    def test_existing_emulator_is_not_restarted(self):
        with patch.object(launcher, "android_sdk", return_value=Path("sdk")), \
             patch.object(launcher, "require", side_effect=lambda path: path), \
             patch.object(launcher, "capture", return_value="Medium_Phone_API_36.1\n"), \
             patch.object(launcher, "running_avd", return_value="emulator-5554"), \
             patch.object(launcher.subprocess, "Popen") as start:
            self.assertEqual(launcher.main(["emulator"]), 0)
            start.assert_not_called()

    def test_app_preserves_exit_code(self):
        with patch.object(launcher, "python_executable", return_value=Path("python.exe")), \
             patch.object(launcher, "require", side_effect=lambda path: path), \
             patch.object(launcher, "android_sdk", return_value=Path("sdk")), \
             patch.object(launcher.subprocess, "call", return_value=7) as call:
            self.assertEqual(launcher.main(["app"]), 7)
            self.assertEqual(call.call_args.kwargs["cwd"], launcher.ROOT)


if __name__ == "__main__":
    unittest.main()
