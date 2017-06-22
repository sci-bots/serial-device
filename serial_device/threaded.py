import platform
import Queue
import sys
import threading
import time

import datetime as dt
import serial
import serial.threaded
import serial_device


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
        print 'connection_made: `%s` `%s`' % (self.port, transport)
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
            print ('Connection to port `%s` lost: %s' % (self.port,
                                                         exception))
            self.connected.clear()
            self.disconnected.set()
        else:
            print 'Connection to port `%s` lost' % self.port


def keep_alive(state, protocol_class, comport, **kwargs):
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
    if comport not in serial_device.comports().index:
        raise NameError('Port `%s` not available.  Available ports: `%s`' %
                        (comport, ', '.join(serial_device.comports().index)))
    while True:
        while comport not in serial_device.comports().index:
            time.sleep(2)
        try:
            device = serial.serial_for_url(comport, **kwargs)
        except serial.SerialException:
            pass
        else:
            with serial.threaded.ReaderThread(device,
                                              protocol_class) as protocol:
                state['protocol'] = protocol

                # Wait for connection.
                protocol.connected.wait()
                # Wait for disconnection.
                protocol.disconnected.wait()


def request(device, response_queue, payload, timeout_s=None, poll=POLL_QUEUES):
    '''
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
        If ``True``, poll response queue in a busy loop until response is ready
        (or timeout occurs).

        Polling is much more processor intensive, but (at least on Windows)
        results in faster response processing.  On Windows, polling is enabled
        by default.
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
