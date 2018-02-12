import queue
import logging
import platform
import threading

import datetime as dt
import serial
import serial.threaded
import serial_device

from .or_event import OrEvent

logger = logging.getLogger(__name__)


# Flag to indicate whether queues should be polled.
# XXX Note that polling performance may vary by platform.
POLL_QUEUES = (platform.system() == 'Windows')


class EventProtocol(serial.threaded.Protocol):
    def __init__(self):
        self.transport = None
        self.connected = threading.Event()
        self.disconnected = threading.Event()
        self.port = None

    def connection_made(self, transport):
        """Called when reader thread is started"""
        self.port = transport.serial.port
        logger.debug('connection_made: `%s` `%s`', self.port, transport)
        self.transport = transport
        self.connected.set()
        self.disconnected.clear()

    def data_received(self, data):
        """Called with snippets received from the serial port"""
        raise NotImplementedError

    def connection_lost(self, exception):
        """\
        Called when the serial port is closed or the reader loop terminated
        otherwise.
        """
        if isinstance(exception, Exception):
            logger.debug('Connection to port `%s` lost: %s', self.port,
                         exception)
        else:
            logger.debug('Connection to port `%s` closed', self.port)
        self.connected.clear()
        self.disconnected.set()


class KeepAliveReader(threading.Thread):
    '''
    Keep a serial connection alive (as much as possible).

    Parameters
    ----------
    state : dict
        State dictionary to share ``protocol`` object reference.
    comport : str
        Name of com port to connect to.
    default_timeout_s : float, optional
        Default time to wait for serial operation (e.g., connect).

        By default, block (i.e., no time out).
    **kwargs
        Keyword arguments passed to ``serial_for_url`` function, e.g.,
        ``baudrate``, etc.
    '''
    def __init__(self, protocol_class, comport, **kwargs):
        super(KeepAliveReader, self).__init__()
        self.daemon = True
        self.protocol_class = protocol_class
        self.comport = comport
        self.kwargs = kwargs
        self.protocol = None
        self.default_timeout_s = kwargs.pop('default_timeout_s', None)

        # Event to indicate serial connection has been established.
        self.connected = threading.Event()
        # Event to request a break from the run loop.
        self.close_request = threading.Event()
        # Event to indicate thread has been closed.
        self.closed = threading.Event()
        # Event to indicate an exception has occurred.
        self.error = threading.Event()
        # Event to indicate that the thread has connected to the specified port
        # **at least once**.
        self.has_connected = threading.Event()

    @property
    def alive(self):
        return not self.closed.is_set()

    def run(self):
        # Verify requested serial port is available.
        try:
            if self.comport not in (serial_device
                                    .comports(only_available=True).index):
                raise NameError('Port `%s` not available.  Available ports: '
                                '`%s`' % (self.comport,
                                          ', '.join(serial_device.comports()
                                                    .index)))
        except NameError as exception:
            self.error.exception = exception
            self.error.set()
            self.closed.set()
            return

        while True:
            # Wait for requested serial port to become available.
            while self.comport not in (serial_device
                                       .comports(only_available=True).index):
                # Assume serial port was disconnected temporarily.  Wait and
                # periodically check again.
                self.close_request.wait(2)
                if self.close_request.is_set():
                    # No connection is open, so nothing to close.  Just quit.
                    self.closed.set()
                    return
            try:
                # Try to open serial device and monitor connection status.
                logger.debug('Open `%s` and monitor connection status',
                             self.comport)
                device = serial.serial_for_url(self.comport, **self.kwargs)
            except serial.SerialException as exception:
                self.error.exception = exception
                self.error.set()
                self.closed.set()
                return
            except Exception as exception:
                self.error.exception = exception
                self.error.set()
                self.closed.set()
                return
            else:
                with serial.threaded.ReaderThread(device, self
                                                  .protocol_class) as protocol:
                    self.protocol = protocol

                    connected_event = OrEvent(protocol.connected,
                                              self.close_request)
                    disconnected_event = OrEvent(protocol.disconnected,
                                                 self.close_request)

                    # Wait for connection.
                    connected_event.wait(None if self.has_connected.is_set()
                                         else self.default_timeout_s)
                    if self.close_request.is_set():
                        # Quit run loop.  Serial connection will be closed by
                        # `ReaderThread` context manager.
                        self.closed.set()
                        return
                    self.connected.set()
                    self.has_connected.set()
                    # Wait for disconnection.
                    disconnected_event.wait()
                    if self.close_request.is_set():
                        # Quit run loop.
                        self.closed.set()
                        return
                    self.connected.clear()
                    # Loop to try to reconnect to serial device.

    def write(self, data, timeout_s=None):
        '''
        Write to serial port.

        Waits for serial connection to be established before writing.

        Parameters
        ----------
        data : str or bytes
            Data to write to serial port.
        timeout_s : float, optional
            Maximum number of seconds to wait for serial connection to be
            established.

            By default, block until serial connection is ready.
        '''
        self.connected.wait(timeout_s)
        self.protocol.transport.write(data)

    def request(self, response_queue, payload, timeout_s=None,
                poll=POLL_QUEUES):
        '''
        Send

        Parameters
        ----------
        device : serial.Serial
            Serial instance.
        response_queue : Queue.Queue
            Queue to wait for response on.
        payload : str or bytes
            Payload to send.
        timeout_s : float, optional
            Maximum time to wait (in seconds) for response.

            By default, block until response is ready.
        poll : bool, optional
            If ``True``, poll response queue in a busy loop until response is
            ready (or timeout occurs).

            Polling is much more processor intensive, but (at least on Windows)
            results in faster response processing.  On Windows, polling is
            enabled by default.
        '''
        self.connected.wait(timeout_s)
        return request(self, response_queue, payload, timeout_s=timeout_s,
                       poll=poll)

    def close(self):
        self.close_request.set()

    # - -  context manager, returns protocol

    def __enter__(self):
        """\
        Enter context handler. May raise RuntimeError in case the connection
        could not be created.
        """
        self.start()
        # Wait for protocol to connect.
        event = OrEvent(self.connected, self.closed)
        event.wait(self.default_timeout_s)
        return self

    def __exit__(self, *args):
        """Leave context: close port"""
        self.close()
        self.closed.wait()


def request(device, response_queue, payload, timeout_s=None, poll=POLL_QUEUES):
    '''
    Send payload to serial device and wait for response.

    Parameters
    ----------
    device : serial.Serial
        Serial instance.
    response_queue : Queue.Queue
        Queue to wait for response on.
    payload : str or bytes
        Payload to send.
    timeout_s : float, optional
        Maximum time to wait (in seconds) for response.

        By default, block until response is ready.
    poll : bool, optional
        If ``True``, poll response queue in a busy loop until response is
        ready (or timeout occurs).

        Polling is much more processor intensive, but (at least on Windows)
        results in faster response processing.  On Windows, polling is
        enabled by default.
    '''
    device.write(payload)
    if poll:
        # Polling enabled.  Wait for response in busy loop.
        start = dt.datetime.now()
        while not response_queue.qsize():
            if (dt.datetime.now() - start).total_seconds() > timeout_s:
                raise queue.Empty('No response received.')
        return response_queue.get()
    else:
        # Polling disabled.  Use blocking `Queue.get()` method to wait for
        # response.
        return response_queue.get(timeout=timeout_s)
