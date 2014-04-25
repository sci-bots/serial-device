from pprint import pprint

from paver.easy import task, needs, path, sh, cmdopts, options
from paver.setuputils import setup, find_package_data, setuptools

import version

setup(name='serial_device',
      version=version.getVersion(),
      description='Simple, cross-platform interface for interacting with '
      'devices through a serial-port.',
      author='Ryan Fobel, Christian Fobel',
      author_email='ryan@fobel.net, christian@fobel.net',
      url='https://github.com/wheeler-microfluidics/serial_device.git',
      license='GPLv2',
      packages=['serial_device'])


@task
@needs('generate_setup', 'minilib', 'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass
