"""Terminal images must not be redrawn during the final TUI render."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mangekyo import banner_image, tui


class BannerExitTest(unittest.TestCase):
    def test_final_render_does_not_draw_crow_or_banner(self):
        output = Mock()
        app = SimpleNamespace(is_done=True, output=output)
        with patch.object(tui, "draw_logo_image") as logo, patch.object(tui, "draw_crow_image") as crow:
            tui._draw_images(app, lambda: True, lambda: False, lambda: True)
        logo.assert_not_called()
        crow.assert_not_called()

    def test_active_render_draws_crow_and_banner(self):
        output = Mock()
        output.get_size.return_value.columns = 120
        app = SimpleNamespace(is_done=False, output=output)
        with patch.object(tui, "draw_logo_image") as logo, patch.object(tui, "draw_crow_image") as crow, \
                patch.object(tui, "image_supported", return_value=True):
            tui._draw_images(app, lambda: True, lambda: False, lambda: True)
        logo.assert_called_once_with(output, 120, stacked=False, top=6)
        crow.assert_called_once_with(output, banner_image.SINGLE_HEIGHT + 7)

    def test_final_banner_render_does_not_write_to_shell(self):
        output = Mock()
        with patch("prompt_toolkit.application.current.get_app_or_none",
                   return_value=SimpleNamespace(is_done=True)):
            banner_image.draw(output, 120, stacked=False)
        output.write_raw.assert_not_called()


class BenchmarkStatusTest(unittest.TestCase):
    def test_verified_saving_shows_reuse_time_and_cache(self):
        report = {"saving_demonstrated": True, "net_model_saving_usd": .0003977,
                  "skipped_steps": ["read_invoice"], "wall_time_saved_ms": 525.44,
                  "provider_cache_saving_usd": 0.0}
        status = tui._langgraph_benchmark_status([report])
        self.assertIn("Model saving $0.0003977", status)
        self.assertIn("1 step skipped", status)
        self.assertIn("525 ms faster", status)
        self.assertIn("provider cache saving $0.0000000", status)

    def test_cheaper_wrong_result_is_not_called_saving(self):
        report = {"saving_demonstrated": False, "net_model_saving_usd": .0003977,
                  "skipped_steps": ["read_invoice"], "wall_time_saved_ms": -25.0,
                  "provider_cache_saving_usd": 0.0}
        status = tui._langgraph_benchmark_status([report])
        self.assertIn("No verified saving", status)
        self.assertNotIn("Model saving $", status)
        self.assertIn("25 ms slower", status)


if __name__ == "__main__":
    unittest.main()
