import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import numpy as np
from PIL import Image

import screenbot


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(screenbot.main(args), 0)
        return output.getvalue().strip()

    @patch("screenbot.mouse_position", return_value=screenbot.Point(12, 34))
    def test_pos(self, _mouse_position):
        self.assertEqual(self.run_cli("pos"), "12 34")
        self.assertEqual(json.loads(self.run_cli("pos", "--json")), {"x": 12, "y": 34})

    @patch("screenbot.pixel_color", return_value=(10, 20, 30))
    @patch("screenbot.mouse_position", return_value=screenbot.Point(12, 34))
    def test_color_at_mouse(self, _mouse_position, _pixel_color):
        self.assertEqual(self.run_cli("color"), "10 20 30 #0A141E")

    @patch("screenbot.screen_size", return_value=(100, 100))
    @patch("screenbot.screenshot")
    @patch("screenbot.mouse_position", return_value=screenbot.Point(50, 50))
    def test_color_square_lists_unique_colors(self, _mouse_position, screenshot, _screen_size):
        pixels = np.array([[(1, 2, 3), (1, 2, 3)], [(4, 5, 6), (1, 2, 3)]], dtype=np.uint8)
        screenshot.return_value = Image.fromarray(pixels, "RGB")

        lines = self.run_cli("color", "-2").splitlines()

        self.assertEqual(lines, ["1 2 3 #010203 3", "4 5 6 #040506 1"])
        screenshot.assert_called_once_with(screenbot.Box(49, 49, 51, 51))


if __name__ == "__main__":
    unittest.main()
