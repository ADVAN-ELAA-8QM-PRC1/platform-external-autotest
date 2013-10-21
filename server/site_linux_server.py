# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import ping_runner
from autotest_lib.server import site_linux_system
from autotest_lib.server.cros import wifi_test_utils

class LinuxServer(site_linux_system.LinuxSystem):
    """
    Linux Server: A machine which hosts network services.

    """

    COMMAND_PING = '/usr/bin/ping'
    COMMAND_NETPERF = '/usr/bin/netperf'
    COMMAND_NETSERVER = '/usr/bin/netserver'


    def __init__(self, server, config):
        site_linux_system.LinuxSystem.__init__(self, server, {}, "server")

        self._server                     = server    # Server host.
        self.vpn_kind                    = None
        self.config                      = config
        self.openvpn_config              = {}
        self.radvd_config                = {'file':'/tmp/radvd-test.conf',
                                            'server':'/usr/sbin/radvd'}

        # Check that tools we require from WiFi test servers exist.
        self._cmd_netperf = wifi_test_utils.must_be_installed(
                self._server, LinuxServer.COMMAND_NETPERF)
        self._cmd_netserver = wifi_test_utils.must_be_installed(
                self._server, LinuxServer.COMMAND_NETSERVER)
        # /usr/bin/ping is preferred, as it is likely to be iputils.
        if wifi_test_utils.is_installed(self._server,
                                        LinuxServer.COMMAND_PING):
            self._cmd_ping = LinuxServer.COMMAND_PING
        else:
            self._cmd_ping = 'ping'

        self._ping_bg_job = None
        self._wifi_ip = None
        self._wifi_if = None
        self._ping_runner = ping_runner.PingRunner(command_ping=self.cmd_ping,
                                                   host=self.host)


    @property
    def cmd_netperf(self):
        """ @return string full path to start netperf. """
        return self._cmd_netperf


    @property
    def cmd_netserv(self):
        """ @return string full path to start netserv. """
        return self._cmd_netserver


    @property
    def cmd_ping(self):
        """ @return string full path to start ping. """
        return self._cmd_ping


    @property
    def server(self):
        """ @return Host object for this remote server. """
        return self._server


    @property
    def wifi_ip(self):
        """Returns an IP address pingable from the client DUT.

        Throws an error if no interface is configured with a potentially
        pingable IP.

        @return String IP address on the WiFi subnet.

        """
        if not self._wifi_ip:
            self.__setup_wifi_interface_info()
        return self._wifi_ip

    @property
    def wifi_if(self):
        """Returns an interface corresponding to self.wifi_ip.

        Throws an error if no interface is configured with a potentially
        pingable IP.

        @return String interface name (e.g. 'mlan0')

        """
        if not self._wifi_if:
            self.__setup_wifi_interface_info()
        return self._wifi_if


    def __setup_wifi_interface_info(self):
        """Parse the output of 'ip -4 addr show' and extract wifi interface/ip.

        This looks something like:

localhost ~ # ip -4 addr show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 16436 qdisc noqueue state UNKNOWN
    inet 127.0.0.1/8 scope host lo
3: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP qlen 1000
    inet 172.22.50.174/24 brd 172.22.50.255 scope global eth0
4: mlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP qlen 1000
    inet 192.168.0.124/24 brd 192.168.0.255 scope global mlan0

        """
        ip_output = self.host.run('%s -4 addr show' % self.cmd_ip).stdout
        regex = re.compile('^inet ([0-9]{1,3}(\\.[0-9]{1,3}){3}).+ '
                           'scope [a-zA-Z]+ ([a-zA-Z0-9]+)$')
        for line in ip_output.splitlines():
            match = re.search(regex, line.strip())
            if not match:
                continue

            # Group 1 will be the IP address following 'inet addr:'.
            ip = match.group(1)
            wifi_if = match.group(3)
            if ip.startswith('127.0.0') or ip.startswith(self.host.ip):
                continue

            logging.debug('Choosing wifi ip/if: %s/%s', ip, wifi_if)
            self._wifi_ip = ip
            self._wifi_if = wifi_if
            return

        raise error.TestFail('No configured interfaces.')


    def vpn_server_config(self, params):
        """ Configure & launch the server side of the VPN.

            Parameters, in 'params':

               kind  : required

                       The kind of VPN which should be configured and
                       launched.

                       Valid values:

                          openvpn
                          l2tpipsec (StrongSwan PSK or certificates)

               config: required

                       The configuration information associated with
                       the VPN server.

                       This is a dict which contains key/value pairs
                       representing the VPN's configuration.

          The values stored in the 'config' param must all be
          supported by the specified VPN kind.

        @param params dict of site_wifitest style parameters.

        """
        self.vpn_server_kill({}) # Must be first.  Relies on self.vpn_kind.
        self.vpn_kind = params.get('kind', None)

        # Launch specified VPN server.
        if self.vpn_kind is None:
            raise error.TestFail('No VPN kind specified for this test.')
        elif self.vpn_kind == 'openvpn':
            # Read config information & create server configuration file.
            for k, v in params.get('config', {}).iteritems():
                self.openvpn_config[k] = v
            self.server.run("cat <<EOF >/tmp/vpn-server.conf\n%s\nEOF\n" %
                            ('\n'.join( "%s %s" % kv for kv in
                                        self.openvpn_config.iteritems())))
            self.server.run("/usr/sbin/openvpn "
                            "--config /tmp/vpn-server.conf &")
        elif self.vpn_kind in ('l2tpipsec-psk', 'l2tpipsec-cert'):
            configs = {
                "/etc/xl2tpd/xl2tpd.conf" :
                "[global]\n"
                "\n"
                "[lns default]\n"
                "  ip range = 192.168.1.128-192.168.1.254\n"
                "  local ip = 192.168.1.99\n"
                "  require chap = yes\n"
                "  refuse pap = yes\n"
                "  require authentication = yes\n"
                "  name = LinuxVPNserver\n"
                "  ppp debug = yes\n"
                "  pppoptfile = /etc/ppp/options.xl2tpd\n"
                "  length bit = yes\n",

                "/etc/xl2tpd/l2tp-secrets" :
                "*      them    l2tp-secret",

                "/etc/ppp/chap-secrets" :
                "chapuser        *       chapsecret      *",

                "/etc/ppp/options.xl2tpd" :
                "ipcp-accept-local\n"
                "ipcp-accept-remote\n"
                "noccp\n"
                "auth\n"
                "crtscts\n"
                "idle 1800\n"
                "mtu 1410\n"
                "mru 1410\n"
                "nodefaultroute\n"
                "debug\n"
                "lock\n"
                "proxyarp\n"
                "connect-delay 5000\n"
            }
            config_choices = {
              'l2tpipsec-psk': {
                  "/etc/ipsec.conf" :
                  "config setup\n"
                  "  charonstart=no\n"
                  "  plutostart=yes\n"
                  "  plutodebug=%(@plutodebug@)s\n"
                  "  plutostderrlog=/var/log/pluto.log\n"
                  "conn L2TP\n"
                  "  keyexchange=ikev1\n"
                  "  authby=psk\n"
                  "  pfs=no\n"
                  "  rekey=no\n"
                  "  left=%(@local-listen-ip@)s\n"
                  "  leftprotoport=17/1701\n"
                  "  right=%%any\n"
                  "  rightprotoport=17/%%any\n"
                  "  auto=add\n",

                  "/etc/ipsec.secrets" :
                  "%(@ipsec-secrets@)s %%any : PSK \"password\"",
                },
                'l2tpipsec-cert': {
                    "/etc/ipsec.conf" :
                    "config setup\n"
                    "  charonstart=no\n"
                    "  plutostart=yes\n"
                    "  plutodebug=%(@plutodebug@)s\n"
                    "  plutostderrlog=/var/log/pluto.log\n"
                    "conn L2TP\n"
                    "  keyexchange=ikev1\n"
                    "  left=%(@local-listen-ip@)s\n"
                    "  leftcert=server.crt\n"
                    "  leftid=\"C=US, ST=California, L=Mountain View, "
                    "CN=chromelab-wifi-testbed-server.mtv.google.com\"\n"
                    "  leftprotoport=17/1701\n"
                    "  right=%%any\n"
                    "  rightca=\"C=US, ST=California, L=Mountain View, "
                    "CN=chromelab-wifi-testbed-root.mtv.google.com\"\n"
                    "  rightprotoport=17/%%any\n"
                    "  auto=add\n"
                    "  pfs=no\n",

                    "/etc/ipsec.secrets" : ": RSA server.key \"\"\n",
                },
            }
            configs.update(config_choices[self.vpn_kind])

            replacements = params.get("replacements", {})
            # These two replacements must match up to the same
            # adapter, or a connection will not be established.
            replacements["@local-listen-ip@"] = "%defaultroute"
            replacements["@ipsec-secrets@"]   = self.server.ip

            for cfg, template in configs.iteritems():
                contents = template % (replacements)
                self.server.run("cat <<EOF >%s\n%s\nEOF\n" % (cfg, contents))

            self.server.run("/usr/sbin/ipsec restart")

            # Restart xl2tpd to ensure use of newly-created config files.
            self.server.run("sh /etc/init.d/xl2tpd restart")
        else:
            raise error.TestFail('(internal error): No config case '
                                 'for VPN kind (%s)' % self.vpn_kind)


    def vpn_server_kill(self, params):
        """Kill the VPN server.

        @param params ignored.

        """
        if self.vpn_kind is not None:
            if self.vpn_kind == 'openvpn':
                self.server.run("pkill /usr/sbin/openvpn")
            elif self.vpn_kind in ('l2tpipsec-psk', 'l2tpipsec-cert'):
                self.server.run("/usr/sbin/ipsec stop")
            else:
                raise error.TestFail('(internal error): No kill case '
                                     'for VPN kind (%s)' % self.vpn_kind)
            self.vpn_kind = None


    def ipv6_server_config(self, params):
        """Start an IPv6 router advertisement daemon.

        @param params dict of site_wifitest style parameters.

        """
        self.ipv6_server_kill({})
        radvd_opts = { 'interface': self.config.get('server_dev', 'eth0'),
                       'adv_send_advert': 'on',
                       'min_adv_interval': '3',
                       'max_adv_interval': '10',
                       # NB: Addresses below are within the 2001:0db8/32
                       # "documentation only" prefix (RFC3849), which is
                       # guaranteed never to be assigned to a real network.
                       'prefix': '2001:0db8:0100:f101::/64',
                       'adv_on_link': 'on',
                       'adv_autonomous': 'on',
                       'adv_router_addr': 'on',
                       'rdnss_servers': '2001:0db8:0100:f101::0001 '
                                        '2001:0db8:0100:f101::0002',
                       'adv_rdnss_lifetime': 'infinity',
                       'dnssl_list': 'a.com b.com' }
        radvd_opts.update(params)

        config = ('interface %(interface)s {\n'
                  '  AdvSendAdvert %(adv_send_advert)s;\n'
                  '  MinRtrAdvInterval %(min_adv_interval)s;\n'
                  '  MaxRtrAdvInterval %(max_adv_interval)s;\n'
                  '  prefix %(prefix)s {\n'
                  '    AdvOnLink %(adv_on_link)s;\n'
                  '    AdvAutonomous %(adv_autonomous)s;\n'
                  '    AdvRouterAddr %(adv_router_addr)s;\n'
                  '  };\n'
                  '  RDNSS %(rdnss_servers)s {\n'
                  '    AdvRDNSSLifetime %(adv_rdnss_lifetime)s;\n'
                  '  };\n'
                  '  DNSSL %(dnssl_list)s {\n'
                  '  };\n'
                  '};\n') % radvd_opts
        cfg_file = params.get('config_file', self.radvd_config['file'])
        self.server.run('cat <<EOF >%s\n%s\nEOF\n' % (cfg_file, config))
        self.server.run('%s -C %s\n' % (self.radvd_config['server'], cfg_file))


    def ipv6_server_kill(self, params):
        """Kill the IPv6 route advertisement daemon.

        @param params ignored.

        """
        self.server.run('pkill %s >/dev/null 2>&1' %
                        self.radvd_config['server'], ignore_status=True)


    def ping(self, ping_config):
        """Ping a client from the server.

        @param ping_config PingConfig object describing the ping command to run.
        @return a PingResult object.

        """
        return self._ping_runner.ping(ping_config)
