import unittest

from silicoin.util.setproctitle import setproctitle


class TestSetProcTitle(unittest.TestCase):
    def test_does_not_crash(self):
        setproctitle("silicoin test title")
