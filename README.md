![https://ci.appveyor.com/api/projects/status/github/wheeler-microfluidics/serial_device?branch=master&svg=true](https://ci.appveyor.com/api/projects/status/github/wheeler-microfluidics/serial_device?branch=master&svg=true)
Serial-device
=============

This package provides a base interface for encapsulating interaction with a
device connected through a serial-port.

It provides methods to automatically resolve a port based on an
implementation-defined connection-test, which is applied to all available
serial-ports until a successful connection is made.

Notes
=====

This package intends to be cross-platform and has been verified to work on
Windows and Ubuntu.
