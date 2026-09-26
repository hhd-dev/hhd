import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import yaml

from hhd.plugins.conf import Config
from hhd.plugins.settings import load_state_yaml, save_state_yaml


class StateFileTest(unittest.TestCase):
    def test_invalid_utf8_uses_default_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.yml")
            with open(path, "wb") as file:
                file.write(b"version: test\n# \xe2\x80")

            self.assertIsNone(load_state_yaml(path, {}))

    def test_failed_save_keeps_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.yml")
            with open(path, "w") as file:
                file.write("version: previous\n")

            def fail_after_partial_write(data, stream, **kwargs):
                stream.write("version: partial\n")
                raise RuntimeError("write failed")

            with patch("yaml.safe_dump", side_effect=fail_after_partial_write):
                with self.assertRaisesRegex(RuntimeError, "write failed"):
                    save_state_yaml(path, {}, Config({}), "current")

            with open(path) as file:
                self.assertEqual(file.read(), "version: previous\n")
            self.assertEqual(os.listdir(directory), ["state.yml"])

    def test_successful_save_replaces_state_and_keeps_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.yml")
            with open(path, "w") as file:
                file.write("version: previous\n")
            os.chmod(path, 0o640)

            self.assertTrue(save_state_yaml(path, {}, Config({}), "current"))
            self.assertEqual(os.listdir(directory), ["state.yml"])
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
            with open(path) as file:
                content = file.read()
            self.assertNotEqual(content, "version: previous\n")
            self.assertIn("version", yaml.safe_load(content))
            self.assertIsNotNone(load_state_yaml(path, {}))


if __name__ == "__main__":
    unittest.main()
