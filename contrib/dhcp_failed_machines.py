#!/usr/bin/python

"""
usage:
./dhcp_failed_machines.py /var/log/dhcp.log

You can also run it directly on the gzip'd logs.

This script basically expects to run from the dhcp machine, as it looks at
/etc/dhcp/dhcpd.conf to be able to do reverse DNS lookups.  It also expects the
dhcp log to be copied to some local file.

If you're lucky, there might still be a copy of this script already on the dhcp
server at /tmp/looky.py.
"""

import gzip
import itertools
import pprint
import re
import sys

lookups = {}

with open('/etc/dhcp/dhcpd.conf', 'r') as f:
  for line in f:
    if line.startswith('#'):
      continue
    if line.split() and line.split()[0] == 'host':
      hostconf = list(itertools.takewhile(lambda x: x.strip() != '}', f))
      d = dict([h.strip().split()[-2:] for h in hostconf])
      hostname = d['ddns-hostname'].replace('"', '').replace(';', '')
      lookups[d['fixed-address'].replace(';', '')] = hostname


offers = {}
offenders = set()

rgx = re.compile(
  r'(?P<command>[A-Z]+) (?:from|on|for) (?P<host>\d+.\d+.\d+.\d+)')

def open_file(f):
  if f.endswith('.gz'):
    return gzip.open(f, 'r')
  else:
    return open(f, 'r')

with open_file(sys.argv[1]) as f:
  for line in f:
    m = rgx.search(line)
    if m:
      command = m.group('command')
      host = m.group('host')
      if command == 'DHCPOFFER':
        offers[host] = offers.get(host, 0) + 1
        if offers[host] > 2:
          offenders.add(host)
      if command == 'DHCPREQUEST':
        offers[host] = 0

def lookup(h):
  return lookups.get(h, h)

pprint.pprint(sorted([lookup(h) for h in offenders]))
