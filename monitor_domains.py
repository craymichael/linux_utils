#!/usr/bin/python
from __future__ import (print_function, absolute_import, unicode_literals,
                        division)
import argparse
import subprocess
import logging
from time import time, sleep

DEFAULT_DOMAINS = []  # list domains here if you don't want to specify via CLI
DEFAULT_POLL_RATE = 5.0  # seconds
DEFAULT_USAGE_THRESH = 0.99  # [0.0, 1.0]
DEFAULT_RESET_AFTER = 30.0  # seconds

logging.basicConfig(level=logging.DEBUG)


def query_cpu_time(domain, t=0.0):
    result = subprocess.run(['virsh', 'cpu-stats', '--total', domain],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    now = time()
    if result.returncode != 0:  # Domain likely not running
        if t != 0.0:
            logging.warning('monitor_domains: Non-zero exit code ({}) from CPU '
                            'time query for domain \'{}\'.'.format(
                result.returncode, domain))
            error_msg = result.stdout.decode('utf-8').strip()
            logging.warning(error_msg)

            if 'domain not found' in error_msg.lower():
                # Domain not running
                logging.warning('Make sure you are running this program as the '
                                'correct user and that the case-sensitive '
                                'domain exists in virsh.')
            print()

        return 0.0, now

    # Parse cpu_time
    cpu_time = float(result.stdout.split(b'\n')[1].split()[1])

    return cpu_time, now


def reset_domain(domain):
    result = subprocess.run(['virsh', 'destroy', domain],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    if result.returncode != 0:  # Domain likely not running
        logging.warning('monitor_domains: Non-zero exit code ({}) from'
                        '\'destroy\' of domain \'{}\'.'.format(
            result.returncode, domain))
        logging.warning(result.stdout.decode('utf-8').strip())
        print()

        return

    result = subprocess.run(['virsh', 'start', domain],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    if result.returncode != 0:  # Bad things
        logging.warning(
            'monitor_domains: Non-zero exit code ({}) from \'start\' '
            'of domain \'{}\'.'.format(result.returncode, domain))
        print(result.stdout.decode('utf-8'))


if __name__ == '__main__':
    # Parser + desc
    parser = argparse.ArgumentParser(
        description='Monitors CPU usage of QEMU/KVM domains using virsh. '
                    'Domains that appear to have locked up are restarted.'
    )
    # Domains parameters
    if len(DEFAULT_DOMAINS):
        d_required = False
        d_help = ' Default:\n{}'.format(DEFAULT_DOMAINS)
        d_kwargs = dict(default=DEFAULT_DOMAINS)
    else:
        d_required = True
        d_help = ''
        d_kwargs = {}
    # Domains
    parser.add_argument(
        '-d', '--domains', nargs='+', metavar='domains', required=d_required,
        help='Comma-separated list of domains found in virsh.{}'.format(d_help),
        **d_kwargs
    )
    # Poll rate
    parser.add_argument(
        '-p', '--poll_rate', metavar='poll_rate', required=False,
        default=DEFAULT_POLL_RATE, type=float,
        help='The time in seconds at which to query a domain\'s status '
             '(default={:.3f}s).'.format(DEFAULT_POLL_RATE)
    )
    # Usage threshold
    parser.add_argument(
        '-t', '--usage_thresh', metavar='usage_thresh', required=False,
        default=DEFAULT_USAGE_THRESH, type=float,
        help='The percentage (in range [0, 1]) of CPU usage to denote a domain '
             'as "locked" (default={:.3f}).'.format(DEFAULT_USAGE_THRESH)
    )
    # Reset after duration
    parser.add_argument(
        '-r', '--reset_after', metavar='reset_after', required=False,
        default=DEFAULT_RESET_AFTER, type=float,
        help='If a domain is marked as "locked" for this duration, it is reset '
             'using the virsh "destroy" and "start" commands '
             '(default={:.3f}s).'.format(DEFAULT_RESET_AFTER)
    )
    # Parse CLI args
    args = parser.parse_args()

    # Init cache
    cache = {domain: query_cpu_time(domain, -1) + (None,)
             for domain in args.domains}

    while True:
        sleep(args.poll_rate)

        for domain in args.domains:
            cpu_time_t1, then, lock_t = cache[domain]
            cpu_time_t0, now = query_cpu_time(domain, cpu_time_t1)
            # Compute usage
            usage = (cpu_time_t0 - cpu_time_t1) / (now - then)
            # Reset logic
            if usage >= args.usage_thresh:
                if lock_t is None:
                    lock_t = now
                elif (now - lock_t) >= args.reset_after:
                    logging.warning(
                        'monitor_domains: Force resetting \'{}\' domain: {} '
                        'seconds of CPU utilization above {}%.'.format(
                            domain, now - lock_t, args.usage_thresh * 100)
                    )
                    reset_domain(domain)
                    lock_t = None
            else:  # Under threshold (not locked up)
                lock_t = None

            # Update cache
            cache[domain] = (cpu_time_t0, now, lock_t,)
