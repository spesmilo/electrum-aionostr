import unittest
import os
import asyncio
from unittest.mock import patch
from logging import getLogger
import json

from electrum_aionostr.relay import Manager, Relay
from electrum_aionostr.key import PrivateKey
from electrum_aionostr.event import Event


_logger = getLogger(__name__)
_logger.setLevel('DEBUG')


def get_random_dummy_event() -> Event:
    privkey = PrivateKey(os.urandom(32))
    event = Event(
        pubkey=privkey.public_key.hex(),
        content="test"
    )
    event.sign(privkey.hex())
    return event


class DummyWebsocket:
    def __init__(self):
        self.incoming_messages = asyncio.Queue()  # data we receive from the relay
        self.outgoing_messages = asyncio.Queue()  # data we send to the relay

    async def receive_str(self):
        msg = await self.incoming_messages.get()
        _logger.debug(f"DummyWebsocket received message")
        return msg

    async def send_str(self, message: str):
        await self.outgoing_messages.put(message)
        _logger.debug(f"DummyWebsocket sent message")

    async def close(self):
        _logger.debug(f"DummyWebsocket closed")


class DummyClientSession:
    def __init__(self):
        self.dummy_websocket = DummyWebsocket()

    async def ws_connect(self, url, origin, ssl):
        _logger.debug(f"DummyClientSession ws connected")
        return self.dummy_websocket

    async def close(self):
        _logger.debug(f"DummyClientSession closed")


class DummyRelay(Relay):
    """Relay without network connections to test the relay manager"""
    def __init__(
        self,
        url: str,
        origin:str = '',
        private_key:str='',
        connect_timeout: float=1.0,
        log=None,
        ssl_context=None,
        proxy=None,
    ):
        Relay.__init__(self, url, origin, private_key, connect_timeout, log, ssl_context, proxy)
        # this will make Relay.connect() use the DummyClientSession instead of an aiohttp ClientSession
        self.client = DummyClientSession()

    def receive_data_from_relay(self, data):
        # put the data on the dummy websocket so the Relay instance treats data as it is appearing
        # on the websocket connection to the connected relay
        self.client.dummy_websocket.incoming_messages.put_nowait(data)


class TestManager(unittest.IsolatedAsyncioTestCase):

    async def test_monitor_queues_event_deduplication(self):
        """
        Tests if the events returned by multiple relays are
        properly deduplicated.
        """
        output_queue = asyncio.Queue()  # this is what the consumer of the subscription will receive
        input_queues = [asyncio.Queue() for _ in range(10)]  # these are the relays
        dummy_events = [get_random_dummy_event() for _ in range(20)]

        for queue in input_queues:
            for dummy_event in dummy_events:
                queue.put_nowait(dummy_event)
            queue.put_nowait(None)

        # Create a patched version of Queue.put that adds a delay to force context
        # switching as it happens with regular usage of monitor_queues
        original_put = asyncio.Queue.put
        async def slow_put(self, item):
            await asyncio.sleep(0.01)
            await original_put(self, item)

        with patch('asyncio.Queue.put', slow_put):
            monitoring_task = asyncio.create_task(Manager.monitor_queues(
                input_queues,
                output_queue,
                set(),
            ))
            # check if the output queue returns some events twice
            event_ids = set()
            while True:
                event = await asyncio.wait_for(output_queue.get(), timeout=10)
                if event is None:
                    break
                assert event.id not in event_ids
                event_ids.add(event.id)

        monitoring_task.cancel()

    async def test_manager_deduplicates_relays(self):
        """
        Relay manager should deduplicate relay urls so it doesn't try to open multiple connections
        to the same relay if it gets passed slightly different URLS.
        This is important as we often have to open connections on-demand with urls parsed from Nostr
        event tags which maybe are slightly different to our own config urls.
        """
        relay_urls = [
            "wss://test.com/",
            "wss://test.com/",
            "wss://test.com",
            "wss://TEST.COM",
            "wSS://test.com",
            "wss://TEST.com",
            "test.com",
            "TEST.COM",
        ]
        manager = Manager(
            relays=relay_urls,
        )
        self.assertEqual(len(manager.relays), 1, msg=[r.url for r in manager.relays])
        self.assertEqual(manager.relays[0].url, "wss://test.com")

    async def test_subscription_gets_closed_on_return(self):
        """Test that get_events properly unsubscribes when exiting its AsyncGenerator"""
        private_key = os.urandom(32)
        with patch('electrum_aionostr.relay.Relay', DummyRelay):
            manager = Manager(
                relays=["wss://dummy.relay" for _ in range(10)],
                private_key=private_key.hex(),
                log=_logger,
            )
        await manager.connect()
        self.assertTrue(manager.connected)
        received_any_event = asyncio.Future()
        async def get_some_events():
            query = {'kinds': [1]}
            async for event in manager.get_events(query, only_stored=False, single_event=False):
                received_any_event.set_result(event)
                # return after we received any event, the subscription should get closed
                return
        event_task = asyncio.create_task(get_some_events())
        while len(manager.subscriptions) < 1:
            # wait until task creates subscription
            await asyncio.sleep(0.01)
        self.assertEqual(len(manager.subscriptions), 1, msg="manger should have exactly one subscription")
        subscription_id = next(iter(manager.subscriptions.keys()))
        # now let the relays send us some events for this subscription
        for i in range(5):
            relay_message = json.dumps(['EVENT', subscription_id, get_random_dummy_event().to_json_object()])
            for dummy_relay in manager.relays:
                dummy_relay.receive_data_from_relay(relay_message)
        await asyncio.wait_for(received_any_event, timeout=0.5)
        # now the subscription task returned, leaving the async generator. the subscription should
        # get closed and cleaned up
        async def wait_for_cleanup():
            while subscription_id in manager.subscriptions:
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait_for_cleanup(), timeout=0.5)
        self.assertTrue(event_task.done())



