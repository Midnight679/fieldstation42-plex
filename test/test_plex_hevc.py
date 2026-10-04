import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fs42.plex_source import PlexClient  # noqa: E402


def client(hevc_max_height=720, **kw):
    c = PlexClient("http://plex.invalid:32400", "t", hevc_max_height=hevc_max_height, **kw)
    versions = {}
    c._media_versions = lambda key: versions[key]
    c._versions = versions
    return c


def media(codec, height, bitrate=2000):
    return {"videoCodec": codec, "height": height, "bitrate": bitrate, "width": height * 16 // 9,
            "Part": [{"key": f"/library/parts/{codec}{height}/file.mkv"}]}


class HevcPlayableTests(unittest.TestCase):
    def test_small_hevc_is_playable_large_is_not(self):
        c = client()
        self.assertTrue(c._playable(media("hevc", 720)))
        self.assertTrue(c._playable(media("hevc", 480)))
        self.assertFalse(c._playable(media("hevc", 1080)))
        self.assertFalse(c._playable(media("hevc", 2160)))

    def test_hevc_with_unknown_height_is_not_playable(self):
        self.assertFalse(client()._playable({"videoCodec": "hevc", "height": None, "bitrate": 1000}))

    def test_setting_zero_turns_hevc_off(self):
        self.assertFalse(client(hevc_max_height=0)._playable(media("hevc", 720)))

    def test_hevc_never_passes_the_overall_height_limit(self):
        c = client(hevc_max_height=2160, max_height=1080)
        self.assertFalse(c._playable(media("hevc", 2160)))
        self.assertTrue(c._playable(media("hevc", 1080)))

    def test_hevc_bitrate_limit_still_applies(self):
        self.assertFalse(client()._playable(media("hevc", 720, 30000)))

    def test_h264_rules_are_unchanged_and_av1_is_never_playable(self):
        c = client()
        self.assertTrue(c._playable(media("h264", 1080)))
        self.assertTrue(c._playable(media("avc", 1088)))
        self.assertFalse(c._playable(media("h264", 2160)))
        self.assertFalse(c._playable(media("av1", 480)))

    def test_h264_copy_is_chosen_over_a_hevc_copy(self):
        c = client()
        c._versions["1"] = [media("hevc", 720), media("h264", 480)]
        url, consumed = c.playback_target("plex://1/x.mkv")
        self.assertIn("h264480", url)
        self.assertEqual(consumed, 0)

    def test_playable_hevc_direct_plays_with_no_transcode(self):
        c = client()
        c._versions["2"] = [media("hevc", 720)]
        url, _ = c.playback_target("plex://2/x.mkv")
        self.assertIn("hevc720", url)
        self.assertNotIn("transcode", url)


if __name__ == "__main__":
    unittest.main()
