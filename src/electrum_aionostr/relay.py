import asyncio
import secrets
import sys
import logging
from json import dumps
from collections import defaultdict, namedtuple
from typing import Optional, Iterable, Dict, List, Set, Any, TYPE_CHECKING, AsyncGenerator
from dataclasses import dataclass
import time

from aiohttp import ClientSession, client_exceptions
import aiorpcx

from .event import Event
from .util import normalize_url

if TYPE_CHECKING:
    from logging import Logger
    from ssl import SSLContext
    from aiohttp_socks import ProxyConnector

# Subscription used inside Relay
Subscription = namedtuple('Subscription', ['filters','queue'])

# Subscription used inside Manager,
@dataclass
class ManagerSubscription:
    output_queue: asyncio.Queue  # queue collects all events from all relays
    filters: tuple[Any, ...]  # filters used to subscribe
    seen_events: Set[bytes]  # event ids we have seen
    monitor: asyncio.Task # monitoring task

class Relay:
    """
    Interact with a relay
    """
    def __init__(self, url: str, origin:str = '', private_key:str='', connect_timeout: float=1.0, log=None, ssl_context=None,
                 proxy: Optional['ProxyConnector']=None):
        self.log = log or logging.getLogger(__name__)
        self.url = normalize_url(url)
        self.proxy = proxy
        self.client = None  # type: Optional[ClientSession]
        self.ws = None
        self.receive_task = None
        self.subscriptions = defaultdict(lambda: Subscription(filters=[], queue=asyncio.Queue()))
        self.event_adds = asyncio.Queue()
        self.notices = asyncio.Queue()
        self.private_key = private_key
        self.origin = origin or url
        self.connected = False
        self.connect_timeout = connect_timeout
        self.ssl_context = ssl_context

    async def connect(self, taskgroup = None, retries=2):
        if not self.client:
            connector_owner = False if self.proxy is not None else True
            self.client = ClientSession(connector=self.proxy, connector_owner=connector_owner)
        for i in range(retries):
            try:
                self.ws = await asyncio.wait_for(
                    self.client.ws_connect(
                        url=self.url,
                        origin=self.origin,
                        ssl=self.ssl_context
                    ),
                    self.connect_timeout)
            except Exception as e:
                self.log.debug(f"Exception on connect: {e!r}")
                if self.ws:
                    await self.ws.close()
                await asyncio.sleep(i ** 2)
            else:
                break
        else:
            self.log.info(f"Cannot connect to {self.url}")
            await self.client.close()
            self.client = None
            return False
        if self.receive_task is None and taskgroup:
            self.receive_task = await taskgroup.spawn(self._receive_messages())
        elif self.receive_task is None:
            self.receive_task = asyncio.create_task(self._receive_messages())
        await asyncio.sleep(0.01)
        self.connected = True
        self.log.info("Connected to %s", self.url)
        return True

    async def reconnect(self):
        while not await self.connect(taskgroup=None, retries=20):
            await asyncio.sleep(60*30)
        for sub_id, sub in self.subscriptions.items():
            self.log.debug("resubscribing to %s", sub.filters)
            await self.send(["REQ", sub_id, *sub.filters])

    async def close(self, taskgroup = None):
        if self.receive_task:
            self.receive_task.cancel() # fixme: this will cancel taskgroup
        if self.ws:
            if taskgroup:
                await taskgroup.spawn(self.ws.close())
            else:
                await self.ws.close()
        if self.client:
            if taskgroup:
                await taskgroup.spawn(self.client.close())
            else:
                await self.client.close()
        self.connected = False

    async def _receive_messages(self):
        while True:
            try:
                message = await asyncio.wait_for(self.ws.receive_json(), 30.0)

                self.log.debug(message)  # FIXME spammy (or at least log which relay it's coming from)
                if message[0] == 'EVENT':
                    await self.subscriptions[message[1]].queue.put(Event(**message[2]))
                elif message[0] == 'EOSE':
                    await self.subscriptions[message[1]].queue.put(None)
                elif message[0] == 'OK':
                    await self.event_adds.put(message)
                elif message[0] == 'NOTICE':
                    await self.notices.put(message[1])
                elif message[0] == 'AUTH':
                    await self.authenticate(message[1])
                else:
                    self.log.debug(f"Unknown message from relay {self.url}: {str(message)}")
            except asyncio.CancelledError:
                return
            except client_exceptions.WSMessageTypeError:  #  raised by receive_json when connection is closed
                await self.reconnect()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.log.exception("")
                await asyncio.sleep(5)

    async def send(self, message):
        try:
            await self.ws.send_str(dumps(message))
        except client_exceptions.ClientConnectionError:
            await self.reconnect()
            await self.ws.send_str(dumps(message))

    async def add_event(self, event, check_response=False):
        if isinstance(event, Event):
            event = event.to_json_object()
        await self.send(["EVENT", event])
        if check_response:
            response = await self.event_adds.get()
            return response[1]

    async def subscribe(self, taskgroup, sub_id: str, *filters, queue=None):
        self.subscriptions[sub_id] = Subscription(filters=filters, queue=queue or asyncio.Queue())
        await taskgroup.spawn(self.send(["REQ", sub_id, *filters]))
        return self.subscriptions[sub_id].queue

    async def unsubscribe(self, sub_id):
        await self.send(["CLOSE", sub_id])
        del self.subscriptions[sub_id]

    async def authenticate(self, challenge:str):
        if not self.private_key:
            import warnings
            warnings.warn("private key required to authenticate")
            return
        from .key import PrivateKey
        if self.private_key.startswith('nsec'):
            from .util import from_nip19
            pk = from_nip19(self.private_key)['object']
        else:
            pk = PrivateKey(bytes.fromhex(self.private_key))
        auth_event = Event(
            kind=22242,
            pubkey=pk.public_key.hex(),
            tags=[
                ['challenge', challenge],
                ['relay', self.url]
            ]
        )
        auth_event.sign(pk.hex())
        await self.send(["AUTH", auth_event.to_json_object()])
        await asyncio.sleep(0.1)
        return True

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, ex_type, ex, tb):
        await self.close()


class Manager:
    """
    Manage a collection of relays
    """
    def __init__(self,
                 relays: Optional[Iterable[str]] = None,
                 origin: Optional[str] = 'aionostr',
                 private_key: Optional[str] = None,
                 log: Optional['Logger'] = None,
                 ssl_context: Optional['SSLContext'] = None,
                 proxy: Optional['ProxyConnector'] = None,
                 connect_timeout: Optional[int] = None):
        self.log = log or logging.getLogger(__name__)
        self._proxy = proxy
        self._connect_timeout = connect_timeout if connect_timeout else 5 if not proxy else 10
        self._ssl_context = ssl_context
        self._private_key = private_key
        self._origin = origin
        self.relays = [Relay(
            r,
            origin=origin,
            private_key=private_key,
            log=log,
            ssl_context=ssl_context,
            proxy=proxy,
            connect_timeout=self._connect_timeout)
            for r in (relays or [])]
        self.subscriptions = {}  # type: Dict[str, ManagerSubscription]
        self._subscription_lock = asyncio.Lock()
        self.connected = False
        self._connectlock = asyncio.Lock()
        self.taskgroup = aiorpcx.TaskGroup()

    @property
    def private_key(self):
        return self._private_key

    @private_key.setter
    def private_key(self, pk):
        for relay in self.relays:
            relay.private_key = pk

    def add(self, url, **kwargs):
        self.relays.append(Relay(url, **kwargs))

    @staticmethod
    async def monitor_queues(queues, output, seen: Set[bytes]):
        async def func(queue):
            while True:
                result = await queue.get()
                if result:
                    eid = result.id_bytes
                    if eid not in seen:
                        seen.add(eid)
                        await output.put(result)
                else:
                    await output.put(None)

        tasks = [func(queue) for queue in queues]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            return

    async def broadcast(self, relays, func, *args, **kwargs):
        """ returns when all tasks completed. timeout is enforced """
        results = []
        for relay in relays:
            coro = asyncio.wait_for(getattr(relay, func)(*args, **kwargs), timeout=self._connect_timeout)
            results.append(await self.taskgroup.spawn(coro))

        if not results:
            return
        self.log.debug("Waiting for %s", func)
        return await asyncio.wait(results, return_when=asyncio.ALL_COMPLETED)

    async def connect(self):
        async with self._connectlock:
            if not self.connected:
                await self.broadcast(self.relays, 'connect', self.taskgroup)
                self.connected = True
                tried = len(self.relays)
                connected = [relay for relay in self.relays if relay.connected]
                success = len(connected)
                self.relays = connected
                self.log.info("Connected to %d out of %d relays", success, tried)

    async def close(self):
        await self.broadcast(self.relays, 'close', self.taskgroup)
        await self.taskgroup.cancel_remaining()
        if self._proxy:
            await self._proxy.close()
            self._proxy = None

    async def add_event(self, event):
        """ waits until one of the tasks succeeds, or raises timeout"""
        queue = asyncio.Queue()
        async def _add_event(relay):
            try:
                result = await relay.add_event(event, check_response=True)
            except Exception as e:
                self.log.info(f'add_event: failed with {relay.url}')
                return
            await queue.put(result)
        for relay in self.relays:
            await self.taskgroup.spawn(_add_event(relay))
        result = await asyncio.wait_for(queue.get(), timeout=self._connect_timeout)
        return result

    async def subscribe(self, sub_id: str, *filters) -> asyncio.Queue[Optional[Event]]:
        """Apply the given filter to all relays and return a queue that collects incoming events"""
        relay_queues = []
        async with self._subscription_lock:
            for relay in self.relays:
                if sub_id not in relay.subscriptions:
                    relay_queues.append(await relay.subscribe(self.taskgroup, sub_id, *filters))
                else:  # relay is already subscribed to this sub_id
                    relay_queues.append(relay.subscriptions[sub_id].queue)

            if not sub_id in self.subscriptions:  # create new output queue
                output_queue = asyncio.Queue()
                seen_events = set()
                subscription = ManagerSubscription(
                    monitor=await self.taskgroup.spawn(self.monitor_queues(relay_queues, output_queue, seen_events)),
                    filters=filters,
                    output_queue=output_queue,
                    seen_events=seen_events)
                self.subscriptions[sub_id] = subscription
            else:  # update existing subscription
                subscription = self.subscriptions[sub_id]
                subscription.monitor.cancel()  # stop the old monitoring task
                output_queue = subscription.output_queue
                subscription.monitor = await self.taskgroup.spawn(  # start a new monitoring task
                    self.monitor_queues(
                        relay_queues,
                        output_queue,
                        subscription.seen_events)
                )
        return output_queue

    async def unsubscribe(self, sub_id):
        async with self._subscription_lock:
            await self.broadcast(self.relays, 'unsubscribe', sub_id)
            self.subscriptions[sub_id].monitor.cancel()
            del self.subscriptions[sub_id]

    async def update_relays(self, updated_relay_list: Iterable[str]) -> None:
        """Dynamically update the relays of an existing Manager instance"""
        if not self.connected:
            raise NotInitialized("Manager is not connected")

        changes: bool = False
        updated_relay_list: Set[str] = set(normalize_url(url) for url in updated_relay_list)
        self.log.debug(f"Updating relays, new list: {updated_relay_list}" )
        # add relays that are not already connected
        new_relays = []
        for relay_url in updated_relay_list:
            if relay_url in [relay.url for relay in self.relays]:
                continue
            new_relay = Relay(
                relay_url,
                origin=self._origin,
                private_key=self._private_key,
                log=self.log,
                ssl_context=self._ssl_context,
                proxy=self._proxy,
                connect_timeout=self._connect_timeout)
            new_relays.append(new_relay)
        if new_relays:
            changes = True
            async with self._connectlock:
                await self.broadcast(new_relays, 'connect', self.taskgroup)
                connected_relays = [relay for relay in new_relays if relay.connected]
                self.relays.extend(connected_relays)
                self.log.info("Connected to %d out of %d new relays", len(connected_relays), len(new_relays))

        # remove relays that are no longer in the updated list
        remove_relays: List[Relay] = []
        for relay in self.relays:
            if relay.url not in updated_relay_list:
                remove_relays.append(relay)
        if remove_relays:
            changes = True
            async with self._connectlock:
                await self.broadcast(remove_relays, 'close', self.taskgroup)
                self.relays = [relay for relay in self.relays if relay not in remove_relays]
                self.log.info("Removed %d relays", len(remove_relays))

        # refresh subscriptions
        if changes:
            for sub_id, subscription in self.subscriptions.items():
                await self.subscribe(sub_id, *subscription.filters)

    async def __aenter__(self):
        await self.taskgroup.__aenter__()
        await self.connect()
        return self

    async def __aexit__(self, ex_type, ex, tb):
        await self.close()
        await self.taskgroup.__aexit__(ex_type, ex, tb)

    async def get_events(
        self,
        *filters,
        only_stored: bool = True,
        single_event: bool = False,
        filter_future_events_sec: Optional[int] = 3600,
    ) -> AsyncGenerator[Event, None]:
        sub_id = secrets.token_hex(4)
        queue = await self.subscribe(sub_id, *filters)
        while True:
            event: Optional[Event] = await queue.get()
            if event is None:
                if only_stored:
                    break
            else:
                # validate event: check signature
                if not event.verify():
                    self.log.debug(f"event {event.id} failed signature verification")
                    continue
                # validate event: timestamp should not be in the future
                if filter_future_events_sec is not None:
                    if event.created_at > time.time() + filter_future_events_sec:
                        self.log.debug(f"event {event.id} too far into future")
                        continue
                yield event
                if single_event:
                    break
        await self.unsubscribe(sub_id)

class NotInitialized(Exception):
    pass

