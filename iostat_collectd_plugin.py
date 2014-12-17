#!/usr/bin/env python
"""Collectd plugin that calls iostat every second.

This plugin is based on the Ruby version by Keiran S <Keiran@gmail.com>.
Please see https://github.com/keirans/collectd-iostat/ for full details.

For each block device line, the fields are reformatted as required for
collectd exec plugins, which can then be graphed using one of the write
plugins, such as write graphite.

Some notes about the output format this plugin requires:

Collectd's exec plugin uses plain text protocol to push data.
* Lines must begin with PUTVAL
* The identifier string must contain a valid type reference that allows
  collectd to be aware of the data type that is being provided.
  This plugin uses the gauge type, which is suitable for positive and
  negative numbers.
* The value we want to graph is printed in the N:<value> format.
  The N translates to epoch time within collectd, followed by a colon
  and the value.
* The iostat command runs with '-Nxk' options.  Thus, all statistics
  are displayed in kilobytes per second instead of blocks per second.
  Keep this in mind when you build graphs and visualize your data.

Exit signals are caught, on which the child process of the plugin is
cleared.  If this is not done, there will be orphaned iostat processes
on the server after a collectd restart.

The plugin should run as 'nobody' via the following exec plugin stanza

<Plugin exec>
   Exec "nobody" "/var/tmp/iostat_collectd_plugin.py"
</Plugin>
"""
__author__ = 'Kevin <kevin@>'
__copyright__ = 'Copyright (c) 2014, Wavefront'

import signal
import socket
import subprocess
import sys


def get_parameters(line):
    """Get parameters output by iostat.

    Args:
        line: Process line, hopefully containing the parameters.

    Returns:
        List of parameter names, cleaned up for transmission, or empty
        list if the parameter names could not be determined.
    """
    params = []
    if 'Device:' in line:
        parts = line.split()
        for part in parts[1:]:
            for character in '/-%':
                if character in part:
                    part = part.replace(character, '_')
            params.append(part)
    return params


def process_line(line, params, hostname):
    """Output iostat line.

    If the line is not a data line, nothing will be shown.

    Args:
        line: The line to parse and output.
        params: A list of parameters contained in the line.
        hostname: Name of the host reporting the data line.
    """
    if line.strip():
        parts = line.split()
        device = parts[0]
        if not ':' in device and len(parts) == len(params) + 1:
            values = parts[1:]
            for index, value in enumerate(values):
                print('PUTVAL %s/iostatplugin/gauge-%s/%s N:%s'
                      % (hostname, device, params[index], value))


def main():
    """Main script.
    """
    def _sigterm_handler(sig_no, stack_frame):
        """Signal handler for process termination.

        Args:
            sig_no: Signal number.
            stack_frame: Stack frame.
        """
        print('Terminating process...')
        process.terminate()

    return_code = 0

    process = subprocess.Popen(['iostat', '-Nxk', '1'], stdout=subprocess.PIPE)
    signal.signal(signal.SIGINT, _sigterm_handler)
    signal.signal(signal.SIGTERM, _sigterm_handler)
    hostname = socket.gethostname().replace('.', '_')
    params = None
    do_it = True
    while do_it:
        line = process.stdout.readline()
        if not line:
            print('No new lines(!).')
            return_code = 1
            do_it = False
        elif params:
            process_line(line, params, hostname)
        else:
            params = get_parameters(line)

    return return_code


if __name__ == '__main__':
    sys.exit(main())
