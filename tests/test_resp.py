from __future__ import annotations

import io
import unittest

from mini_redis.resp import RespError, RespReader


class RespReaderTest(unittest.TestCase):
    def test_reads_valid_resp_command(self) -> None:
        reader = RespReader(io.BytesIO(b"*2\r\n$4\r\nPING\r\n$4\r\ntest\r\n"))

        command = reader.read_command()

        self.assertEqual(command, [b"PING", b"test"])

    def test_rejects_negative_multibulk_length(self) -> None:
        reader = RespReader(io.BytesIO(b"*-1\r\n"))

        with self.assertRaisesRegex(RespError, "invalid multibulk length"):
            reader.read_command()

    def test_rejects_bulk_length_less_than_minus_one(self) -> None:
        reader = RespReader(io.BytesIO(b"*1\r\n$-2\r\n"))

        with self.assertRaisesRegex(RespError, "invalid bulk length"):
            reader.read_command()

    def test_rejects_null_bulk_string_in_command(self) -> None:
        reader = RespReader(io.BytesIO(b"*1\r\n$-1\r\n"))

        with self.assertRaisesRegex(RespError, "null bulk string is not supported in commands"):
            reader.read_command()

    def test_rejects_incomplete_bulk_data(self) -> None:
        reader = RespReader(io.BytesIO(b"*1\r\n$4\r\nPI"))

        with self.assertRaisesRegex(RespError, "incomplete bulk data"):
            reader.read_command()

    def test_rejects_unexpected_end_of_stream_while_reading_bulk_length(self) -> None:
        reader = RespReader(io.BytesIO(b"*1\r\n"))

        with self.assertRaisesRegex(RespError, "unexpected end of stream"):
            reader.read_command()


if __name__ == "__main__":
    unittest.main()
