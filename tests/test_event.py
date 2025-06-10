import unittest
import os
import time

from electrum_aionostr.event import Event
from electrum_aionostr.key import PrivateKey

class TestEvent(unittest.TestCase):

    def test_verify(self):
        privkey1 = PrivateKey(os.urandom(32))
        privkey2 = PrivateKey(os.urandom(32))

        event = Event(
            pubkey=privkey1.public_key.hex(),
            content="test"
        )
        # verify event without signature
        self.assertFalse(event.verify())
        # verify event with correct signature
        event.sign(privkey1.hex())
        self.assertTrue(event.verify())
        # verify event with incorrect signature
        event.sign(privkey2.hex())
        self.assertFalse(event.verify())

    def test_expiration(self):
        privkey1 = PrivateKey(os.urandom(32))
        event = Event(
            pubkey=privkey1.public_key.hex(),
            content="test"
        )

        # Test event with no expiration tag
        self.assertFalse(event.is_expired())

        # Test event with expiration tag set in the future
        future_time = int(time.time()) + 3600
        event.tags = []
        event.add_expiration_tag(future_time)
        self.assertFalse(event.is_expired())

        # Test event with expiration tag set in the past
        event.tags = [["expiration", str(int(time.time()) - 3600)]]
        self.assertTrue(event.is_expired())

        # Test event with expiration tag set during initialization
        future_time = int(time.time()) + 999999
        event_with_expiration = Event(
            pubkey=privkey1.public_key.hex(),
            content="test",
            expiration_ts=future_time
        )
        self.assertFalse(event_with_expiration.is_expired())
        self.assertEqual(future_time, event_with_expiration.expires_at())

        # test expired event with multiple tags
        expiration_time = int(time.time())
        event.tags = []
        event.tags.append(["test", "test"])
        event.tags.append(["test"])
        event.tags.append(["test", 21312, "test"])
        event.tags.append(["expiration", str(expiration_time)])
        event.tags.append(["test", "test"])
        event.tags.append(["test"])
        event.tags.append(["test", 21312, "test"])

        self.assertTrue(event.is_expired())
        self.assertEqual(event.expires_at(), expiration_time)
