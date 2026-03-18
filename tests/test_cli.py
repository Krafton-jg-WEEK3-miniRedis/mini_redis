from __future__ import annotations

import io
import threading
import unittest

from mini_redis.cli import EMPTY_INPUT_MESSAGE, WELCOME_LINES, run_interactive
from mini_redis.server import MiniRedisTCPServer
from mini_redis.storage import HashTableStore


class MiniRedisCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MiniRedisTCPServer(("127.0.0.1", 0), store=HashTableStore())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_interactive_prints_welcome_banner(self) -> None:
        answers = iter(["EXIT"])
        output = io.StringIO()

        exit_code = run_interactive(
            self.host,
            self.port,
            input_func=lambda _: next(answers),
            out=output,
        )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        for line in WELCOME_LINES:
            self.assertIn(line, rendered)

    def test_interactive_shows_hint_for_blank_input(self) -> None:
        answers = iter(["   ", "EXIT"])
        output = io.StringIO()

        exit_code = run_interactive(
            self.host,
            self.port,
            input_func=lambda _: next(answers),
            out=output,
        )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn(EMPTY_INPUT_MESSAGE, rendered)


if __name__ == "__main__":
    unittest.main()
