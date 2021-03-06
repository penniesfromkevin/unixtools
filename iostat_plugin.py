#!/usr/bin/env python
"""Collectd plugin that calls iostat every so often (settable).

This plugin is based on the Ruby version by Keiran S <Keiran@gmail.com>.
Please see https://github.com/keirans/collectd-iostat/ for full details.

For each block device line, the fields are reformatted as required for
collectd 'exec' plugins, which can then be graphed using one of the
'write' plugins, such as 'write graphite'.

Some notes about the output format this plugin requires:

Collectd's 'exec' plugin uses plain-text protocol to push data.
* Lines must begin with PUTVAL
* The identifier string must contain a valid type reference that allows
  collectd to be aware of the data type that is being provided.
  This plugin uses the gauge type, which is suitable for positive and
  negative numbers.
* The value is printed in the 'N:<value>' format.
  The N translates to epoch time within collectd, followed by a colon
  and the value.
* The default iostat command runs with '-Nxk' options: all statistics
  are displayed in kilobytes per second instead of blocks per second.
  Keep this in mind when building graphs and visualizing the data.

Exit signals are caught, at which the child process of the plugin is
terminated.  If this is not done, there will be orphaned iostat
processes on the server after a collectd restart.

The plugin can run as 'nobody' via the following 'exec' plugin stanza

<Plugin exec>
   Exec "nobody" "/var/tmp/iostat_collectd_plugin.py"
</Plugin>
"""
__author__ = 'Kevin <penniesfromkevin@>'
__copyright__ = 'Copyright (c) 2014, Kevin'

import argparse
import logging
import signal
import socket
import subprocess
import sys


DEFAULT_DELAY = 1 # seconds
DEFAULT_IOSTAT = 'Nxk'

AGENTS = ('collectd', 'graphite')
DEFAULT_AGENT = AGENTS[0]
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 2878

LOG_LEVELS = ('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG')
DEFAULT_LOG_LEVEL = LOG_LEVELS[3]
LOGGER = logging.getLogger()


def parse_args():
    """Parse user arguments and return as parser object.

    Returns:
        Parser object with arguments as attributes.
    """
    parser = argparse.ArgumentParser(description='iostat collectd plugin.')
    parser.add_argument('-c', '--get_cpu', action='store_true',
            help='Track average CPU statistics when flag is set.')
    parser.add_argument('-n', '--hostname',
            help='Hostname to use instead of actual name.')
    parser.add_argument('-i', '--iostat_options', default=DEFAULT_IOSTAT,
            help='Options to pass to iostat (default: %s).' % DEFAULT_IOSTAT)
    parser.add_argument('-d', '--delay', default=DEFAULT_DELAY, type=int,
            help='Delay between iostat queries, in seconds (default: %d).'
                 % DEFAULT_DELAY)

    parser.add_argument('-a', '--agent', default=DEFAULT_AGENT,
            help='Type of agent to send data (default: %s).' % DEFAULT_AGENT)
    parser.add_argument('-s', '--host', default=DEFAULT_HOST,
            help='IP of machine running agent.')
    parser.add_argument('-p', '--port', default=DEFAULT_PORT, type=int,
            help='Agent port receiving data.')
    parser.add_argument('-e', '--emit', action='store_true',
            help='Send points to agent for real.')

    parser.add_argument('-L', '--loglevel', choices=LOG_LEVELS,
            default=DEFAULT_LOG_LEVEL, help='Set the logging level.')
    args = parser.parse_args()
    return args


def get_parameters(line):
    """Get parameters output by iostat.

    Args:
        line: Process line, hopefully containing the parameters.

    Returns:
        Tuple: (param_type, param_list)
        Where:
            param_type is one of ('avg-cpu:', 'Device:')
            param_list is a list of parameter names cleaned up for
                transmission, or empty list if the parameters could not
                be determined.
    """
    param_type = None
    param_list = []
    parts = line.split()
    if parts and parts[0] in ('avg-cpu:', 'Device:'):
        param_type = parts[0]
        for part in parts[1:]:
            for character in '/-%':
                if character in part:
                    part = part.replace(character, '_')
            param_list.append(part)
    return param_type, param_list


def extract_line_data(line, params):
    """Extract iostat data.

    If the line is not a data line, nothing will be extracted.

    Args:
        line: The line to parse.
        params: A list of parameters expected in the line.

    Returns:
        A list of data objects.  Each object contains:
            device: Device to which the data belong.
            param: Parameter being measured.
            value: Value of the parameter being measured.
    """
    return_data = []
    if line.strip():
        LOGGER.debug(line)
        parts = line.split()
        if len(parts) == len(params) + 1:
            device = parts[0]
            values = parts[1:]
        elif len(parts) == len(params):
            device = 'cpu'
            values = parts
        else:
            device = None

        if device:
            for index, value in enumerate(values):
                datum = {
                        'device': device,
                        'param': params[index],
                        'value': value,
                        }
                return_data.append(datum)
    return return_data


def output_data(data, agent, hostname, host=None, port=None, emit=False):
    """Output data to the specified agent.

    Args:
        data: List of data objects.
        agent: Type of agent to use.
        hostname: Name of host to which the data belong.
        host: Agent host address.
        port: Agent port.
        emit: Boolean; if False, the data will only be shown on screen.
    """
    if agent == 'graphite':
        template = "iostat.{1}.{2} {3} host='{0}'"
    else:
        template = 'PUTVAL {0}/iostat/gauge-{1}/{2} N:{3}'
    for datum in data:
        line = template.format(hostname, datum['device'], datum['param'],
                               datum['value'])
        if emit and agent == 'graphite':
            transmit_line(host, port, line)
        print(line)


def transmit_line(host, port, line):
    """Transmit data line to metrics agent.

    Args:
        host: Host IP.
        port: Host port.
        line: Metric line to send, in Graphite format.
    """
    sock = socket.socket()
    sock.connect((host, port))
    sock.sendall('%s\n' % line)
    sock.close()


def main():
    """Main script.
    """
    def _sigterm_handler(sig_no, _stack_frame):
        """Signal handler for process termination.

        Args:
            sig_no: Signal number.
            stack_frame: Stack frame.
        """
        print('Terminating process... (%s)' % sig_no)
        process.terminate()

    return_code = 0

    iostat_options = '-%s' % ARGS.iostat_options.strip('-')
    process = subprocess.Popen(['iostat', iostat_options, str(ARGS.delay)],
                               stdout=subprocess.PIPE)
    signal.signal(signal.SIGINT, _sigterm_handler)
    signal.signal(signal.SIGTERM, _sigterm_handler)
    if ARGS.hostname:
        hostname = ARGS.hostname
    else:
        hostname = socket.gethostname().replace('.', '_')
    io_stats = None
    do_it = True
    while do_it:
        line = process.stdout.readline()
        if not line:
            print('No new lines(!).')
            return_code = 1
            do_it = False
        elif io_stats:
            data = extract_line_data(line, io_stats)
            if data:
                output_data(data, ARGS.agent, hostname, ARGS.host, ARGS.port,
                            ARGS.emit)
            else:
                io_stats = None
        else:
            stat_type, io_stats = get_parameters(line)
            if not ARGS.get_cpu and stat_type == 'avg-cpu:':
                io_stats = None
            LOGGER.debug('%s --> %s', stat_type, io_stats)

    return return_code


if __name__ == '__main__':
    ARGS = parse_args()
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
                        level=getattr(logging, ARGS.loglevel))
    sys.exit(main())
