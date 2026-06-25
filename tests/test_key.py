from hashlib import sha256
import unittest
from unittest.mock import patch

from electrum_aionostr.key import PrivateKey, PublicKey, CryptoBackendUnavailableError


bfh = bytes.fromhex


class TestKey(unittest.TestCase):

    def test_basics(self):
        nsec = 'nsec1yc7ftz6k59mwnnl2chvh7lth9sz208tl8mygn29t98dcg5dg8avsqg7xh4'
        npub = 'npub1aq9rl4v66ch3xxrv9n4gunlvqjxgnpqsyhvath4ee3d2z9k55t8s8z6dnu'
        secret_bytes = bfh("263c958b56a176e9cfeac5d97f7d772c04a79d7f3ec889a8ab29db8451a83f59")
        pubkey_bytes = bfh("e80a3fd59ad62f13186c2cea8e4fec048c89841025d9d5deb9cc5aa116d4a2cf")

        privkey1 = PrivateKey.from_nsec(nsec)
        privkey2 = PrivateKey(secret_bytes)
        self.assertEqual(secret_bytes, privkey1.raw_secret)
        self.assertEqual(secret_bytes, privkey2.raw_secret)
        self.assertEqual(secret_bytes.hex(), privkey1.hex())

        pubkey1 = privkey1.public_key
        pubkey2 = PublicKey(pubkey_bytes)
        pubkey3 = PublicKey.from_npub(npub)
        self.assertEqual(npub, pubkey1.bech32())
        self.assertEqual(npub, pubkey2.bech32())
        self.assertEqual(npub, pubkey3.bech32())
        self.assertEqual(pubkey_bytes.hex(), pubkey1.raw_bytes.hex())
        self.assertEqual(pubkey_bytes.hex(), pubkey1.hex())
        self.assertEqual(pubkey_bytes.hex(), pubkey2.hex())
        self.assertEqual(pubkey_bytes.hex(), pubkey3.hex())

    def test_sign_message_hash(self):
        secret_bytes = bfh("263c958b56a176e9cfeac5d97f7d772c04a79d7f3ec889a8ab29db8451a83f59")
        privkey = PrivateKey(secret_bytes)
        msg_hash = sha256(b"hello there").digest()
        sig_hex = privkey.sign_message_hash(msg_hash)

        pubkey = privkey.public_key
        self.assertTrue(pubkey.verify_signed_message_hash(msg_hash.hex(), sig_hex))
        self.assertFalse(pubkey.verify_signed_message_hash(msg_hash.hex(), bytes(64).hex()))
        self.assertFalse(pubkey.verify_signed_message_hash(msg_hash.hex(), bytes(range(64)).hex()))

    def test_encrypt_message(self):
        privkey1 = PrivateKey(bfh("263c958b56a176e9cfeac5d97f7d772c04a79d7f3ec889a8ab29db8451a83f59"))
        privkey2 = PrivateKey(bfh("80a20c6f606010d4e259cae4c0231bab26da25f7e5497bb21a9d48298d0603da"))
        msg1 = "hello there"
        ciphertext = privkey1.encrypt_message(msg1, privkey2.public_key.hex())
        self.assertEqual(msg1, privkey2.decrypt_message(ciphertext, privkey1.public_key.hex()))
        self.assertEqual(msg1, privkey1.decrypt_message(ciphertext, privkey2.public_key.hex()))

    def test_crypto_backend_unavailable(self):
        with patch('electrum_aionostr.key.AES_AVAILABLE', False):
            key = PrivateKey()
            random_pubkey = PrivateKey().public_key
            key.compute_shared_secret(random_pubkey.hex())  # test some other functionality, shouldn't raise
            with self.assertRaises(CryptoBackendUnavailableError):
                key.encrypt_message(message="test", public_key_hex=random_pubkey.hex())
            with self.assertRaises(CryptoBackendUnavailableError):
                key.decrypt_message(encoded_message="test", public_key_hex=random_pubkey.hex())
