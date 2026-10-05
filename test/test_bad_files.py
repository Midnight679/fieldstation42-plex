import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fs42 import bad_files  # noqa: E402


class BadFilesTests(unittest.TestCase):
    def setUp(self):
        bad_files._failures.clear()
        bad_files._skipped_at.clear()

    def test_one_failure_is_forgiven(self):
        self.assertFalse(bad_files.record_failure("a.mp4", now=100))
        self.assertFalse(bad_files.is_bad("a.mp4", now=101))

    def test_second_failure_in_a_row_skips_the_file(self):
        bad_files.record_failure("a.mp4", now=100)
        self.assertTrue(bad_files.record_failure("a.mp4", now=130))
        self.assertTrue(bad_files.is_bad("a.mp4", now=131))

    def test_other_files_are_not_affected(self):
        bad_files.record_failure("a.mp4", now=100)
        bad_files.record_failure("a.mp4", now=130)
        self.assertFalse(bad_files.is_bad("b.mp4", now=131))

    def test_a_skipped_file_gets_another_chance_after_the_wait(self):
        bad_files.record_failure("a.mp4", now=100)
        bad_files.record_failure("a.mp4", now=130)
        self.assertTrue(bad_files.is_bad("a.mp4", now=130 + bad_files.RETRY_AFTER - 1))
        self.assertFalse(bad_files.is_bad("a.mp4", now=130 + bad_files.RETRY_AFTER))
        # and the count starts afresh: one more failure is forgiven again
        self.assertFalse(bad_files.record_failure("a.mp4", now=130 + bad_files.RETRY_AFTER + 5))

    def test_a_success_clears_the_record(self):
        bad_files.record_failure("a.mp4", now=100)
        bad_files.record_success("a.mp4")
        self.assertFalse(bad_files.record_failure("a.mp4", now=200))   # counts as the first failure again

    def test_the_skip_is_reported_only_once(self):
        bad_files.record_failure("a.mp4", now=100)
        self.assertTrue(bad_files.record_failure("a.mp4", now=130))
        self.assertFalse(bad_files.record_failure("a.mp4", now=131))


def _station_player_class():
    """StationPlayer without mpv, the guide window or the web renderer (none of them exist on a test machine)."""
    names = ("python_mpv_jsonipc", "fs42.guide_tk", "fs42.webrender", "fs42.webrender.web_render", "fs42.reception",
             "fs42.autobump_agent", "fs42.liquid_manager", "fs42.liquid_schedule", "fs42.station_manager",
             "fs42.slot_reader", "fs42.plex_source", "fs42.block_plan")
    # the stand-ins exist only while the module is imported, so they cannot leak into other tests
    with patch.dict(sys.modules, {name: MagicMock() for name in names}):
        sys.modules.pop("fs42.station_player", None)
        from fs42.station_player import StationPlayer, PlayerState
    return StationPlayer, PlayerState


class WaitOutUnplayableTests(unittest.TestCase):
    def setUp(self):
        self.StationPlayer, self.PlayerState = _station_player_class()
        self.player = types.SimpleNamespace(
            station_config={"standby_image": "runtime/standby.png"}, played=[], commands=[],
            handle_runtime_command_outcome=lambda r: False, is_non_interrupting=lambda r: False)
        self.player.play_file = lambda path, *a, **k: self.player.played.append(path) or True
        self.player.input_check_fn = lambda: self.player.commands.pop(0) if self.player.commands else None
        self.entry = types.SimpleNamespace(path="plex://924/x.mkv", duration=0.3)

    def test_shows_the_standby_picture_then_returns_when_the_time_is_up(self):
        result = self.StationPlayer._wait_out_unplayable(self.player, self.entry, 0)
        self.assertIsNone(result)
        self.assertEqual(self.player.played, ["runtime/standby.png"])

    def test_a_channel_change_ends_the_wait_and_is_handed_back(self):
        change = types.SimpleNamespace(status=self.PlayerState.CHANNEL_CHANGE, payload=None)
        self.player.commands = [change]
        self.entry.duration = 30
        self.assertIs(self.StationPlayer._wait_out_unplayable(self.player, self.entry, 0), change)

    def test_an_offset_past_the_end_still_waits_a_moment_and_returns(self):
        self.entry.duration = 1
        self.assertIsNone(self.StationPlayer._wait_out_unplayable(self.player, self.entry, 5))


if __name__ == "__main__":
    unittest.main()
