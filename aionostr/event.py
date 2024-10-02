"""
forked from https://github.com/jeffthibault/python-nostr.git
"""
import time
import functools
from enum import IntEnum
import electrum_ecc as ecc
from electrum_ecc import ECPrivkey, ECPubkey
from hashlib import sha256

try:
    import rapidjson

    loads = rapidjson.loads
    dumps = functools.partial(rapidjson.dumps, ensure_ascii=False)
except ImportError:
    import json

    loads = json.loads
    dumps = functools.partial(json.dumps, separators=(",", ":"), ensure_ascii=False)


class EventKind(IntEnum):
    SET_METADATA = 0
    TEXT_NOTE = 1
    RECOMMEND_RELAY = 2
    CONTACTS = 3
    ENCRYPTED_DIRECT_MESSAGE = 4
    DELETE = 5


class Event:
    __slots__ = (
        "id",
        "pubkey",
        "created_at",
        "kind",
        "content",
        "tags",
        "sig",
    )

    def __init__(
        self,
        pubkey: str = "",
        content: str = "",
        created_at: int = 0,
        kind: int = EventKind.TEXT_NOTE,
        tags: "list[list[str]]" = [],
        id: str = None,
        sig: str = None,
    ) -> None:
        if not isinstance(content, str):
            raise TypeError("Argument 'content' must be of type str")

        self.pubkey = pubkey
        self.content = content
        self.created_at = created_at or int(time.time())
        self.kind = int(kind)
        self.tags = tags
        self.sig = sig
        if not id:
            id = Event.compute_id(
                self.pubkey, self.created_at, self.kind, self.tags, self.content
            )
        self.id = id

    @property
    def id_bytes(self):
        return bytes.fromhex(self.id)

    @property
    def is_ephemeral(self):
        return self.kind >= 20000 and self.kind < 30000

    @property
    def is_replaceable(self):
        return self.kind >= 10000 and self.kind < 20000

    @property
    def is_paramaterized_replaceable(self):
        return self.kind >= 30000 and self.kind < 40000

    @staticmethod
    def serialize(
        public_key: str,
        created_at: int,
        kind: int,
        tags: "list[list[str]]",
        content: str,
    ) -> bytes:
        data = [0, public_key, created_at, kind, tags, content]
        data_str = dumps(data)
        return data_str.encode()

    @staticmethod
    def compute_id(
        public_key: str,
        created_at: int,
        kind: int,
        tags: "list[list[str]]",
        content: str,
    ) -> str:
        return sha256(
            Event.serialize(public_key, created_at, kind, tags, content)
        ).hexdigest()

    def sign(self, private_key_hex: str) -> None:
        sk = ECPrivkey(bytes.fromhex(private_key_hex))
        sig = sk.schnorr_sign(bytes.fromhex(self.id))
        self.sig = sig.hex()

    def verify(self) -> bool:
        try:
            pub_key = ECPubkey(bytes.fromhex(self.pubkey))
        except Exception as e:
            return False
        event_id = Event.compute_id(
            self.pubkey, self.created_at, self.kind, self.tags, self.content
        )

        verified = pub_key.schnorr_verify(
            bytes.fromhex(self.sig),
            bytes.fromhex(event_id),
        )
        for tag in self.tags:
            if tag[0] == "delegation":
                # verify delegation signature
                _, delegator, conditions, sig = tag
                to_sign = (
                    ":".join(["nostr", "delegation", self.pubkey, conditions])
                ).encode("utf8")
                delegation_verified = PublicKey(bytes.fromhex(delegator)).verify(
                    bytes.fromhex(sig),
                    sha256(to_sign).digest(),
                )
                if not delegation_verified:
                    return False
        return verified

    def has_tag(self, tag_name: str, matches: list = None) -> (bool, str):
        """
        Given a tag name and optional list of matches to find, return (found, match)
        """
        found_tag = False
        match = None
        for tag in self.tags:
            if tag[0] == tag_name:
                found_tag = True
                if matches and len(tag) > 1 and tag[1] in matches:
                    match = tag[1]
        return found_tag, match

    def to_message(self, sub_id: str = None):
        message = ["EVENT"]
        if sub_id:
            message.append(sub_id)
        message.append(self.to_json_object())
        return dumps(message)

    def __str__(self):
        return dumps(self.to_json_object())

    def to_json_object(self) -> dict:
        return {
            "id": self.id,
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "kind": self.kind,
            "tags": self.tags,
            "content": self.content,
            "sig": self.sig,
        }
