import logging
import platform
import Queue
import sys
import threading
import time

import datetime as dt
import serial
import serial.threaded
import serial_device

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
        # Event to indicate serial connection has been established.
        self.connected = threading.Event()

    def run(self):
        # Verify requested serial port is available.
        if self.comport not in serial_device.comports().index:
            raise NameError('Port `%s` not available.  Available ports: `%s`' %
                            (self.comport,
                             ', '.join(serial_device.comports().index)))
        while True:
            # Wait for requested serial port to become available.
            while self.comport not in serial_device.comports().index:
                # Assume serial port was disconnected temporarily.  Wait and
                # periodically check again.
                time.sleep(2)
            try:
                # Try to open serial device and monitor connection status.
                device = serial.serial_for_url(self.comport, **self.kwargs)
            except serial.SerialException:
                pass
            else:
                with serial.threaded.ReaderThread(device, self
                                                  .protocol_class) as protocol:
                    self.protocol = protocol

                    # Wait for connection.
                    protocol.connected.wait()
                    self.connected.set()
                    # Wait for disconnection.
                    protocol.disconnected.wait()
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

    # - -  context manager, returns protocol

    def __enter__(self):
        """\
        Enter context handler. May raise RuntimeError in case the connection
        could not be created.
        """
        self.start()
        # Wait for protocol to connect.
        self.connected.wait()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Leave context: close port"""
        self.close()


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
                raise Queue.Empty('No response received.')
        return response_queue.get()
    else:
        # Polling disabled.  Use blocking `Queue.get()` method to wait for
        # response.
        return response_queue.get(timeout=timeout_s)
