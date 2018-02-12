'''
Copyright 2014 Christian Fobel
Copyright 2011 Ryan Fobel

This file is part of serial_device.

serial_device is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

serial_device is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with serial_device.  If not, see <http://www.gnu.org/licenses/>.
'''
from time import sleep
import itertools
import os
import types

import pandas as pd
import path_helpers as ph
import serial.tools.list_ports

from ._version import get_versions
__version__ = get_versions()['version']
del get_versions


def _comports():
    '''
    Returns
    -------
    pandas.DataFrame
        Table containing descriptor, and hardware ID of each available COM
        port, indexed by port (e.g., "COM4").
    '''
    return (pd.DataFrame(map(list, serial.tools.list_ports.comports()),
                         columns=['port', 'descriptor', 'hardware_id'])
            .set_index('port'))


def comports(vid_pid=None, include_all=False, check_available=True,
             only_available=False):
    '''
    .. versionchanged:: 0.9
        Add :data:`check_available` keyword argument to optionally check if
        each port is actually available by attempting to open a temporary
        connection.

        Add :data:`only_available` keyword argument to only include ports that
        are actually available for connection.

    Parameters
    ----------
    vid_pid : str or list, optional
        One or more USB vendor/product IDs to match.

        Each USB vendor/product must be in the form ``'<vid>:<pid>'``.
        For example, ``'2341:0010'``.
    include_all : bool, optional
        If ``True``, include all available serial ports, but sort rows such
        that ports matching specified USB vendor/product IDs come first.

        If ``False``, only include ports that match specified USB
        vendor/product IDs.
    check_available : bool, optional
        If ``True``, check if each port is actually available by attempting to
        open a temporary connection.
    only_available : bool, optional
        If ``True``, only include ports that are available.

    Returns
    -------
    pandas.DataFrame
        Table containing descriptor and hardware ID of each COM port, indexed
        by port (e.g., "COM4").

        .. versionchanged:: 0.9
            If :data:`check_available` is ``True``, add an ``available`` column
            to the table indicating whether each port accepted a connection.
    '''
    df_comports = _comports()

    # Extract USB product and vendor IDs from `hwid` entries of the form:
    #
    #     FTDIBUS\VID_0403+PID_6001+A60081GEA\0000
    df_hwid = (df_comports.hardware_id.str.lower().str
               .extract('vid_(?P<vid>[0-9a-f]+)\+pid_(?P<pid>[0-9a-f]+)',
                        expand=True))
    # Extract USB product and vendor IDs from `hwid` entries of the form:
    #
    #     USB VID:PID=16C0:0483 SNR=2145930
    no_id_mask = df_hwid.vid.isnull()
    df_hwid.loc[no_id_mask] = (df_comports.loc[no_id_mask, 'hardware_id']
                               .str.lower().str
                               .extract('vid:pid=(?P<vid>[0-9a-f]+):'
                                        '(?P<pid>[0-9a-f]+)', expand=True))
    df_comports = df_comports.join(df_hwid)

    if vid_pid is not None:
        if isinstance(vid_pid, types.StringTypes):
            # Single USB vendor/product ID specified.
            vid_pid = [vid_pid]

        # Mark ports that match specified USB vendor/product IDs.
        df_comports['include'] = (df_comports.vid + ':' +
                                  df_comports.pid).isin(map(str.lower,
                                                            vid_pid))

        if include_all:
            # All ports should be included, but sort rows such that ports
            # matching specified USB vendor/product IDs come first.
            df_comports = (df_comports.sort_values('include', ascending=False)
                           .drop('include', axis=1))
        else:
            # Only include ports that match specified USB vendor/product IDs.
            df_comports = (df_comports.loc[df_comports.include]
                           .drop('include', axis=1))

    if check_available or only_available:
        # Add `available` column indicating whether each port accepted a
        # connection.  A port may not, for example, accept a connection if the
        # port is already open.
        available = []

        for name_i, port_info_i in df_comports.iterrows():
            try:
                connection = serial.Serial(port=name_i)
                connection.close()
                available.append(True)
            except serial.SerialException:
                available.append(False)
        df_comports['available'] = available
        if only_available:
            df_comports = df_comports.loc[df_comports.available]
        if not check_available:
            del df_comports['available']
    return df_comports


def get_serial_ports():
    if os.name == 'nt':
        ports = _get_serial_ports_windows()
    else:
        ports = itertools.chain(ph.path('/dev').walk('ttyUSB*'),
                                ph.path('/dev').walk('ttyACM*'),
                                ph.path('/dev').walk('tty.usb*'))
    # sort list alphabetically
    ports_ = [port for port in ports]
    ports_.sort()
    for port in ports_:
        yield port


def _get_serial_ports_windows():
    '''
    Uses the Win32 registry to return a iterator of serial (COM) ports existing
    on this computer.

    See http://stackoverflow.com/questions/1205383/listing-serial-com-ports-on-windows
    '''
    import _winreg as winreg

    reg_path = 'HARDWARE\\DEVICEMAP\\SERIALCOMM'
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
    except WindowsError:
        # No serial ports. Return empty generator.
        return

    for i in itertools.count():
        try:
            val = winreg.EnumValue(key, i)
            yield str(val[1])
        except EnvironmentError:
            break


class ConnectionError(Exception):
    pass


class SerialDevice(object):
    '''
    This class provides a base interface for encapsulating interaction with a
    device connected through a serial-port.

    It provides methods to automatically resolve a port based on an
    implementation-defined connection-test, which is applied to all available
    serial-ports until a successful connection is made.

    Notes
    =====

    This class intends to be cross-platform and has been verified to work on
    Windows and Ubuntu.
    '''
    def __init__(self):
        self.port = None

    def get_port(self, baud_rate):
        '''
        Using the specified baud-rate, attempt to connect to each available
        serial port.  If the `test_connection()` method returns `True` for a
        port, update the `port` attribute and return the port.

        In the case where the `test_connection()` does not return `True` for
        any of the evaluated ports, raise a `ConnectionError`.
        '''
        self.port = None

        for test_port in get_serial_ports():
            if self.test_connection(test_port, baud_rate):
                self.port = test_port
                break
            sleep(0.1)

        if self.port is None:
            raise ConnectionError('Could not connect to serial device.')

        return self.port

    def test_connection(self, port, baud_rate):
        '''
        Test connection to device using the specified port and baud-rate.

        If the connection is successful, return `True`.
        Otherwise, return `False`.
        '''
        raise NotImplementedError
