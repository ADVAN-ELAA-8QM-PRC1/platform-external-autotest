# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, re

def isBSDRouter(router):
    router_uname = router.run('uname').stdout
    return re.search('BSD', router_uname)

def find_ifnet(host, pattern):
    list = host.run("ifconfig -l").stdout
    for ifnet in list.split():
        status = host.run("ifconfig %s" % ifnet).stdout
        m = re.search(pattern, status)
        if m:
            return ifnet
    return None

class NotImplemented(Exception):
    def __init__(self, what):
        self.what = what
    def __str__(self):
        return repr("Test method '%s' not implemented" % self.what)


class BSDRouter(object):
    """
    BSD-style WiFi Router support for WiFiTest class.

    This class implements test methods/steps that communicate with a
    router implemented with FreeBSD 8.0 and later.  The router must
    be pre-configured to enable ssh access and have a net80211-based
    wireless device.  We also assume hostapd is present for handling
    authenticator duties and any necessary modules are pre-loaded
    (e.g. wlan_ccmp, wlan_tkip, wlan_wep, wlan_xauth).
    """


    def __init__(self, host, params, defssid):
        self.router = host
        # default to 1st available wireless nic
        if "phydev" not in params:
            self.phydev = find_ifnet(host, ".*media:.IEEE.802.11.*")
            if self.phydev is None:
                raise Exception("No wireless NIC found")
        else:
            self.phydev = params['phydev']
        # default to 1st available wired nic
        if "wiredev" not in params:
            self.wiredif = find_ifnet(host, ".*media:.Ethernet.*")
            if self.wiredif is None:
                raise Exception("No wired NIC found")
        else:
            self.wiredif = params['wiredev']
        self.defssid = defssid;
        self.ssid = defssid
        self.wlanif = None
        self.bridgeif = None

        self.hostapd_keys = ("wpa", "wpa_passphrase", "wpa_key_mgmt",
            "wpa_pairwise", "wpa_group_rekey", "wpa_strict_rekey",
            "wpa_gmk_rekey", "wpa_ptk_rekey",
            "rsn_pairwise",
            "rsn_preauth", "rsh_preauth_interfaces",
            "peerkey")
        self.hostapd_conf = None

        # clear any previous state; this is a hack
        self.router.run("ifconfig wlan0 destroy >/dev/null 2>&1",
            ignore_status=True)
        self.router.run("ifconfig bridge0 destroy >/dev/null 2>&1",
            ignore_status=True)
        self.router.run("killall hostapd >/dev/null 2>&1", ignore_status=True)

    def create(self, params):
        """ Create a wifi device of the specified type """

        phydev = params.get('phydev', self.phydev)
        result = self.router.run("ifconfig wlan create wlandev %s" \
            " wlanmode %s" % (phydev, params['type']))
        self.wlanif = result.stdout[:-1]

        # NB: can't create+addm together 'cuz of ifconfig bug
        result = self.router.run("ifconfig bridge create")
        self.bridgeif = result.stdout[:-1]
        result = self.router.run("ifconfig %s addm %s addm %s" % \
            (self.bridgeif, self.wlanif, self.wiredif))
        logging.info("Use '%s' for %s mode vap and '%s' for bridge",
            self.wlanif, params['type'], self.bridgeif)


    def destroy(self, params):
        """ Destroy a previously created device """

        if self.wlanif is not None:
            self.deconfig(params)
            self.router.run("ifconfig %s destroy" % self.wlanif, \
                ignore_status=True)
        if self.bridgeif is not None:
            self.router.run("ifconfig %s destroy" % self.bridgeif, \
                ignore_status=True)


    def __get_args(self, params):
        #
        # Convert test parameters to ifconfig arguments.  These
        # mostly are passed through unchanged; the wep keys must
        # be mapped.
        #
        args = ""
        for (k, v) in params.items():
            if v is None:
                args += " %s" % k
            elif k == "wep_key0":
                args += " wepkey 1:0x%s" % v
            elif k == "wep_key1":
                args += " wepkey 2:0x%s" % v
            elif k == "wep_key2":
                args += " wepkey 3:0x%s" % v
            elif k == "wep_key3":
                args += " wepkey 4:0x%s" % v
            elif k == "deftxkey":
                args += " deftxkey %s" % str(int(v)+1)
            else:
                args += " %s '%s'" % (k, v)
        return args


    def config(self, params):
        """
        Configure the AP per test requirements.  This can be done
        entirely with ifconfig unless we need an authenticator in
        which case we must also setup hostapd.
        """

        if 'ssid' not in params:
            params['ssid'] = self.defssid + params.get('ssid_suffix', '')
        self.ssid = params['ssid']

        args = ""
        hostapd_args = ""
        if "wpa" in params:
            #
            # WPA/RSN requires hostapd as an authenticator; split out
            # ifconfig args from hostapd configuration and setup to
            # construct the hostapd.conf file below.
            #
            for (k, v) in params.items():
                if k in self.hostapd_keys:
                    if v is None:
                        hostapd_args += "%s\n" % k
                    else:
                        hostapd_args += "%s=%s\n" % (k, v)
                else:
                    if v is None:
                        args += " %s" % k
                    else:       # XXX wep_key?
                        args += " %s %s" % (k, v)

        else:
            args += self.__get_args(params)

        # configure the interface and mark it up
        self.router.run("ifconfig %s %s up" % (self.wlanif, args))

        if hostapd_args is not "":
            #
            # Construct the hostapd.conf file and start hostapd;
            # note this must come after the interface is configured
            # so hostapd can adopt information such as the ssid.
            #
            self.hostapd_conf = "/tmp/%s.conf" % self.wlanif
            self.router.run("cat<<'EOF' >%s\ninterface=%s\n%sEOF\n" % \
                (self.hostapd_conf, self.wlanif, hostapd_args))
            self.router.run("hostapd -B %s" % self.hostapd_conf)
        else:
            self.hostapd_conf = None

        # finally bring the bridge up
        self.router.run("ifconfig %s up" % self.bridgeif)


    def deconfig(self, params):
        """ De-configure the AP (typically marks wlanif down) """

        self.router.run("ifconfig %s down" % self.wlanif)
        if self.hostapd_conf is not None:
            self.router.run("killall hostapd >/dev/null 2>&1")
            self.router.run("rm -f %s" % self.hostapd_conf)
            self.hostapd_conf = None


    def router_monitor_start(self, params):
        """ Start monitoring system events """
        raise NotImplemented("monitor_start")


    def router_monitor_stop(self, params):
        """ Stop monitoring system events """
        raise NotImplemented("monitor_stop")


    def router_check_event_mic(self, params):
        """ Check for MIC error event """
        raise NotImplemented("check_client_event_mic")


    def router_check_event_countermeasures(self, params):
        """ Check for WPA CounterMeasures event """
        raise NotImplemented("check_client_event_countermeasures")


    def router_force_mic_error(self, params):
        """
        Force a Michael MIC error on the next packet.  Note this requires
        a driver that uses software crypto and a kernel with the support
        to fire oneshot MIC errors (first appeared in FreeBSD 8.1).
        """
        raise NotImplemented("force_mic_error")

    def get_ssid(self):
        return self.ssid
