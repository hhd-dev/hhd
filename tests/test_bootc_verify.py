import unittest
from pathlib import Path

import yaml

SETTINGS_FN = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "hhd"
    / "plugins"
    / "bootc"
    / "settings.yml"
)


def load_settings():
    with open(SETTINGS_FN, "r") as f:
        return yaml.safe_load(f)


def walk(node, path=""):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")


def stage_children(settings, mode):
    return settings["children"]["stage"]["modes"][mode]["children"]


class BootcVerifyTagsTest(unittest.TestCase):
    """Destructive bootc actions must carry `tags: [verify]` so the UI
    asks for confirmation before running them (issue #348)."""

    def setUp(self):
        self.settings = load_settings()

    def assert_has_verify(self, mode, action):
        node = stage_children(self.settings, mode)[action]
        self.assertIn(
            "verify",
            node.get("tags") or [],
            f"stage mode '{mode}' action '{action}' lacks the verify tag",
        )

    def test_revert_to_previous_requires_verify(self):
        for mode in ("ready", "ready_rebased", "ready_check"):
            self.assert_has_verify(mode, "revert")

    def test_undo_update_and_undo_revert_require_verify(self):
        self.assert_has_verify("ready_updated", "revert")
        self.assert_has_verify("ready_reverted", "revert")

    def test_rpm_ostree_reset_requires_verify(self):
        self.assert_has_verify("incompatible", "reset")

    def test_update_to_stable_requires_verify(self):
        self.assert_has_verify("unknown", "update")

    def test_reboot_still_requires_verify(self):
        self.assert_has_verify("ready_updated", "reboot")
        self.assert_has_verify("ready_reverted", "reboot")

    def test_no_singular_tag_key_anywhere(self):
        # `tag:` (singular) is not read by the UI, so a confirmation
        # written that way never shows. Only `tags:` is valid.
        for path, node in walk(self.settings):
            self.assertNotIn(
                "tag",
                node,
                f"singular 'tag:' key at {path} is ignored by the UI",
            )


if __name__ == "__main__":
    unittest.main()
