"""Исправленный WebSocket-класс для mattermostdriver.

mattermostdriver 7.3.2 (не обновляется с 2022) создаёт SSL-контекст с
``Purpose.CLIENT_AUTH`` — это контекст для *серверной* стороны, и современный
Python отказывается открывать с ним клиентское соединение:
``Cannot create a client socket with a PROTOCOL_TLS_SERVER context``.

Здесь ``connect()`` скопирован из ``mattermostdriver.websocket.Websocket``
с единственной правкой: клиентский контекст ``ssl.create_default_context()``.
Подключается через ``driver.init_websocket(handler, websocket_cls=ClientTLSWebsocket)``.
"""

import asyncio
import logging
import ssl

import websockets
from mattermostdriver.websocket import Websocket

log = logging.getLogger("mattermostdriver.websocket")


class ClientTLSWebsocket(Websocket):
    async def connect(self, event_handler):
        # Правка: клиентский TLS-контекст (по умолчанию Purpose.SERVER_AUTH).
        # В отличие от оригинала, верификация сертификата не отключается:
        # для self-signed сертификатов добавьте CA в системное хранилище доверия.
        context = ssl.create_default_context()

        scheme = "wss://"
        if self.options["scheme"] != "https":
            scheme = "ws://"
            context = None

        url = "{scheme:s}{url:s}:{port:s}{basepath:s}/websocket".format(
            scheme=scheme,
            url=self.options["url"],
            port=str(self.options["port"]),
            basepath=self.options["basepath"],
        )

        self._alive = True

        while True:
            try:
                kw_args = {}
                if self.options["websocket_kw_args"] is not None:
                    kw_args = self.options["websocket_kw_args"]
                websocket = await websockets.connect(
                    url,
                    ssl=context,
                    **kw_args,
                )
                await self._authenticate_websocket(websocket, event_handler)
                while self._alive:
                    try:
                        await self._start_loop(websocket, event_handler)
                    except websockets.ConnectionClosedError:
                        break
                if (not self.options["keepalive"]) or (not self._alive):
                    break
            except Exception as e:
                log.warning(f"Failed to establish websocket connection: {e}")
                await asyncio.sleep(self.options["keepalive_delay"])
