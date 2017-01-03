import sys

from paver.easy import path, task, needs
from paver.setuputils import setup

sys.path.insert(0, path(__file__).realpath().parent)
import version

setup(name='serial_device',
      version=version.getVersion(),
      description='Simple, cross-platform interface for interacting with '
      'devices through a serial-port.',
      author='Ryan Fobel, Christian Fobel',
      author_email='ryan@fobel.net, christian@fobel.net',
      install_requires=['pandas>=0.18', 'pyserial'],
      url='https://github.com/wheeler-microfluidics/serial_device.git',
      license='GPLv2',
      packages=['serial_device'])


@task
@needs('generate_setup', 'minilib', 'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass


@task
@needs('generate_setup', 'minilib', 'setuptools.command.bdist_wheel')
def bdist_wheel():
    """Overrides bdist_wheel to make sure that our setup.py is generated."""
    pass
