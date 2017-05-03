################################################################################
#                             _    ____ _     ___                              #
#                            / \  / ___| |   |   |                             #
#                           / _ \| |   | |    | |                              #
#                          / ___ \ |___| |___ | |                              #
#                         /_/   \_\____|_____|___|                             #
#                                                                              #
#                                                                              #
################################################################################
#                                                                              #
# Copyright 2016 Evolvere Technologies Ltd                                     #
#                                                                              #
#    Licensed under the Apache License, Version 2.0 (the "License"); you may   #
#    not use this file except in compliance with the License. You may obtain   #
#    a copy of the License at                                                  #
#                                                                              #
#         http://www.apache.org/licenses/LICENSE-2.0                           #
#                                                                              #
#    Unless required by applicable law or agreed to in writing, software       #
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT #
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the  #
#    License for the specific language governing permissions and limitations   #
#    under the License.                                                        #
#                                                                              #
################################################################################

import cobra.mit.access
import cobra.mit.session
import cobra.mit.request
import cobra.model.config
import cobra.model.fabric
import cobra.model.pol
import requests
import re
import sys
import datetime
from requests.packages.urllib3.exceptions import InsecureRequestWarning, InsecurePlatformWarning, SNIMissingWarning
from cmd import Cmd
from operator import attrgetter
from getpass import getpass
from prettytable import PrettyTable


try:
    from settings.aci_settings import FABRICS
except:
    sys.exit('ERROR: Missing or incorrect aci_settings.py file.')

SHOW_CMDS = ['epg', 'interface', 'vlan', 'snapshot']
SHOW_EPG_CMDS = ['NAME', 'all|ALL']
SHOW_VLAN_CMDS = ['pools', '<vlan_id>']
SHOW_INTF_CMDS = ['<node>', ]
CONFIG_CMDS = ['snapshot', ]
CONFIG_SNAPSHOT = ['<snapshot_id>', 'new']


class Apic(Cmd):
    def __init__(self):
        Cmd.__init__(self)
        import readline
        readline.set_completer_delims(' ')
        if 'libedit' in readline.__doc__:
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")
        self.can_connect = ''
        self.fabric = []
        self.snapshots = []
        self.leafs = []
        self.epg_names = []
        self.vlan_pools = []
        self.idict = {}
        self.epgs = []
        self.refresh_time_epoch = 0
        self.username = ''
        self.password = ''
        self.address = ''

    def do_login(self, args):
        """Usage: login [FABRIC_NAME]"""
        if self.can_connect:
            try:
                self.disconnect()
            except:
                pass

        self.can_connect = ''

        if len(args) == 0:
            print "Usage: login [FABRIC_NAME]"    
        else:
            parameters = args.split()
            if parameters[0] in FABRICS.keys():
                self.fabric = FABRICS[parameters[0]]
                self.username = ''
                self.password = ''
                for apic_credentials in self.fabric:
                    if not apic_credentials['username'] or not apic_credentials['password']:
                        if not self.username and not self.password:
                            self.username = raw_input('Enter username: ')
                            self.password = getpass()
                    else:
                        self.username = apic_credentials['username']
                        self.password = apic_credentials['password']

                    self.address = apic_credentials['address']
                    try:
                        self.connect()
                        self.can_connect = parameters[0]
                        print 'Established connection to APIC in', self.can_connect
                        self.prompt = 'ACLI({})>'.format(self.can_connect)
                        break
                    except Exception as error:
                        print 'ERROR', str(error)
                        pass
                if not self.can_connect:
                    print 'Cannot connect to APIC in', parameters[0]

    def do_config(self, args):
        """
        Performs basic admin configuration tasks for Cisco ACI
        Usage:
        config snapshot new | <snapshot_id>
        """
        if self.can_connect:
            if len(args) == 0:
                print "Usage: config snapshot <id>. "
            elif 'snapshot' in args:
                parameters = args.split()
                if (len(parameters) == 2) and ('new' in parameters[1]):
                    description = raw_input('Enter description for the snapshot: ')
                    status = self.create_snapshot(description)
                    if status[0] == 0:
                        print 'Snapshot has been successfully created'
                    else:
                        print 'ERROR: failed to create new snapshot'

                elif (len(parameters) == 2) and (int(parameters[1]) + 1 <= len(self.snapshots)):
                    snapshot_id = parameters[1]
                    description = raw_input('Enter new description for the snapshot: ')
                    status = self.update_snapshot_description(snapshot_id, description)
                    if status[0] == 0:
                        print 'Description has been successfully updated for snapshot ID', snapshot_id
                    else:
                        print 'ERROR: failed to update description for snapshot ID', snapshot_id
                else:
                    print 'Usage: config snapshot <id>.'
        else:
            print 'Login to a Fabric'
        return

    def do_show(self, args):
        """
        Retrieves information from Cisco ACI
        Usage:
        show epg [<epg_name>]
        show interface [<node>] [<leaf_interface, i.e. 1/10>]
        show vlan <vlan_id> | pool
        show snapshot
        """
        if self.can_connect:
            if len(args) == 0:
                print "Usage: show epg, show interfaces or show vlan."
            elif 'epg'in args:
                parameters = args.split()
                if len(parameters) >= 2:
                    if parameters[1] in self.epg_names:
                        epg = parameters[1]
                    else:
                        epg='ALL'
                else:
                    epg='ALL'
                self.get_epg_data(epg)
                self.get_interface_data()
                self.print_epgs()
            elif 'interface' in args:
                parameters = args.split()
                if len(parameters) >= 2:
                    if (len(parameters) == 2) and (parameters[1] in self.leafs):
                        self.get_interface_data(parameters[1])
                        self.print_interface()
                    elif (len(parameters) == 3) and (parameters[1] in self.leafs):
                        self.get_interface_data(parameters[1])
                        self.get_epg_data(epg='ALL')
                        try:
                            idx = int(parameters[1]) * 1000 + int(parameters[2].split('/')[0]) * 100 + \
                                  int(parameters[2].split('/')[-1])

                            if idx in self.idict:
                                self.print_interface_details(idx)
                            else:
                                print 'ERROR: Interface is not present on the Node or not a LEAF port', parameters[1]
                        except Exception as error:
                            print 'ERROR: ', str(error)

                    else:
                        print 'ERROR: Incorrect Node or Interface'
                else:
                    self.get_interface_data()
                    self.print_interface()
            elif 'snapshot' in args:
                self.print_snapshot()
            elif 'vlan' in args:
                parameters = args.split()
                if len(parameters) == 2 and 'pool' not in parameters[1]:
                    try:
                       vlan_id = int(parameters[1])
                       if (vlan_id >= 1) and (vlan_id <= 4096):
                            self.get_epg_data('ALL')
                            self.get_vlan_pool()
                            self.vlan_usage(vlan_id)
                       else:
                           print 'VLAN needs to be 1-4096'
                    except Exception as error:
                       print str(error)
                elif len(parameters) == 2 and 'pool' in parameters[1]:
                    self.get_vlan_pool()
                    self.print_vlan_pool()
                else:
                    print 'Usage: show vlan pools or show vlan [VLAN]'
        else:
            print 'Login to a Fabric'
        return

    def complete_config(self, text, line, begidx, endidx):

        if begidx == 7:
            if text:
                return [i for i in CONFIG_CMDS if i.startswith(text)]
            else:
                return CONFIG_CMDS

        if begidx == 16 and 'snapshot' in line:
            if text:
                return [i for i in CONFIG_SNAPSHOT if i.startswith(text)]
            else:
                return CONFIG_SNAPSHOT

    def complete_show(self, text, line, begidx, endidx):

        if begidx == 5:
            if text:
                return [i for i in SHOW_CMDS if i.startswith(text)]
            else:
                return SHOW_CMDS

        if begidx == 9 and 'epg' in line:
            if text:
                return [i for i in self.epg_names if i.startswith(text)]
            else:
                return self.epg_names
        
        if begidx == 10 and 'vlan' in line:
            if text:
                return [i for i in SHOW_VLAN_CMDS if i.startswith(text)]
            else:
                return SHOW_VLAN_CMDS

        if begidx == 15 and 'interface' in line:
            if text:
                return [i for i in self.leafs if i.startswith(text)]
            else:
                return self.leafs

    def complete_login(self, text, line, begidx, endidx):
        if begidx == 6 and 'login' in line:
            if text:
                return [i for i in FABRICS if i.startswith(text)]
            else:
                return FABRICS.keys()

    def do_quit(self, args):
        """Quits the program."""
        print "Leaving ACLI."
        self.disconnect()
        raise SystemExit

    def emptyline(self):
        pass

    def connect(self):

        self.ls = cobra.mit.session.LoginSession('https://' + self.address, self.username, self.password)
        self.md = cobra.mit.access.MoDirectory(self.ls)
        self.md.login()
        # self.refresh_time_epoch = int(self.ls.refreshTime)
        self.refresh_time_epoch = int(datetime.datetime.now().strftime('%s'))
        self.collect_epgs()
        self.collect_leafs()

    def refresh_connection(self, timeout=90):
        try:
            current_time_epoch = int(datetime.datetime.now().strftime('%s'))

            if current_time_epoch - self.refresh_time_epoch >= timeout:
                self.connect()
            else:
                self.md.login()
                self.refresh_time_epoch = current_time_epoch

            return [0, ]

        except:
            print 'Lost connection to Fabric', self.can_connect
            self.can_connect = ''
            apic.prompt = 'ACLI()>'
            return [1, ]

    def disconnect(self):
        try:
            self.md.logout()
        except:
            pass
        apic.prompt = 'ACLI()>'

    def collect_epgs(self):
        resp = self.md.lookupByClass('fvAEPg', '')
        self.epg_names = []
        for epg in resp:
            self.epg_names.append(str(epg.name))

    def collect_leafs(self):
        resp = self.md.lookupByClass('fabricNode', '')
        self.leafs = []
        for node in resp:
            if str(node.role) == 'leaf':
                self.leafs.append(str(node.id))
    
    def collect_snapshots(self):

        result = self.refresh_connection()

        if result[0] == 1:
            return

        self.snapshots = []
        snapshots_unsorted = self.md.lookupByClass('configSnapshot', '')
        self.snapshots = sorted(snapshots_unsorted, key=attrgetter("createTime"), reverse=True)
        return    

    def create_snapshot(self, description):

        result = self.refresh_connection()

        if result[0] == 1:
            return

        pol_uni = cobra.model.pol.Uni('')
        fabric_inst = cobra.model.fabric.Inst(pol_uni)
        cobra.model.config.ExportP(fabric_inst, targetDn='', name='defaultOneTime', adminSt='triggered',
                                   snapshot='true', descr=description)
        c = cobra.mit.request.ConfigRequest()
        c.addMo(fabric_inst)
        try:
            self.md.commit(c)
            return [0, ]
        except:
            pass
            return [1, ]

    def update_snapshot_description(self, snapshot_id, description):

        result = self.refresh_connection()

        if result[0] == 1:
            return

        snapshot = self.snapshots[int(snapshot_id)]
        snapshot.descr = description
        c = cobra.mit.request.ConfigRequest()
        c.addMo(snapshot)
        try:
            self.md.commit(c)
            return [0, ]
        except:
            return [1, ]
    
    def get_epg_data(self, epg):

        result = self.refresh_connection()

        if result[0] == 1:
            return

        self.epgs = []
        if epg:
            if epg == 'ALL':
                resp = self.md.lookupByClass('fvAEPg', '', subtree='children')
            else:
                resp = self.md.lookupByClass('fvAEPg', '', propFilter='eq( fvAEPg.name, "{0}")'.format(epg),
                                             subtree='children')
            for epg in resp:
                paths = []
                tags = []
                name = str(epg.name)
                tn = str(epg.dn).split('/')[1].replace('tn-', '')
                ap = str(epg.dn).split('/')[2].replace('ap-', '')
                if epg.numChildren > 0:
                    for child in epg.children:
                        if 'RsPathAtt' in str(child.__class__):
                            encap = str(child.encap).replace('vlan-', '')
                            if 'protpaths' in str(child.tDn):
                                protpaths = str(child.tDn).split('/')[2]
                                vpc = str(child.tDn).split('/')[-1].split('[')[-1][:-1]
                                path_dict = {'vpc': vpc, 'protpaths': protpaths, 'encap': encap, 'idx': 0}
                                paths.append(path_dict)

                            elif 'paths' in str(child.tDn):
                                intf_id = str(child.tDn).split('eth')[-1][:-1]
                                node = str(child.tDn).split('/')[2].replace('paths-', '')
                                idx = int(node)*1000 + int(str(intf_id).split('/')[0])*100 +\
                                    int(str(intf_id).split('/')[-1])
                                path_dict = {'idx': idx, 'node': node, 'intf_id': intf_id, 'encap': encap}
                                paths.append(path_dict)

                        elif 'tag' in str(child.dn):
                            tags.append(str(child.dn).split('/')[-1].replace('tag-', ''))

                        elif 'RsBd' in str(child.__class__):
                            bd = str(child.tnFvBDName)

                paths_sorted = sorted(paths, key=lambda k: k['idx'])
                epg_dict = {'name': name, 'tn': tn, 'ap': ap, 'bd': bd, 'paths': paths_sorted, 'tags': tags}
                self.epgs.append(epg_dict)
    
    def get_interface_data(self, target_node=''):

        result = self.refresh_connection()

        if result[0] == 1:
            return

        port_profiles = {}
        port_to_switch_prof_map = {}

        resp = self.md.lookupByClass('infraRtAccPortP', 'uni/infra')
        for item in resp:
            sw_sel = str(item.tDn).split('/')[2].replace('nprof-', '')
            int_sel = str(item.dn).split('/')[2].replace('accportprof-', '')

            port_to_switch_prof_map.setdefault(int_sel, []).append(sw_sel)

        resp = self.md.lookupByClass('infraNodeBlk', 'uni/infra')

        switch_prof_leaves = {}

        for item in resp:

            sw_sel = str(item.dn).split('/')[2].replace('nprof-', '')
            for node in range(int(item.from_), int(item.to_) + 1):
                switch_prof_leaves.setdefault(sw_sel, []).append(node)

        resp = self.md.lookupByClass('infraHPortS', 'uni/infra', subtree='children')

        access_port_selectors = {}

        for item in resp:

            isl = str(item.dn).split('/')[2].replace('accportprof-', '')

            hport_name = str(item.name)
            interfaces = []
            if item.numChildren > 0:
                pol_grp = ''
                for child in item.children:

                    if 'RsAccBaseGrp' in str(child.__class__):
                        pol_grp = str(child.tDn).split('-', 1)[-1]
                    elif 'PortBlk' in str(child.__class__):
                        for intf in range(int(child.fromPort), int(child.toPort) + 1):
                            intf_name = '1/' + str(intf)
                            interfaces.append(intf_name)

                access_port_selectors.setdefault(isl, []).append({'hport_name' : hport_name, 'policy_group': pol_grp,
                                                'interfaces': interfaces})

        for port_selector in access_port_selectors:
            if port_selector in port_to_switch_prof_map:
                for port_selector_item in access_port_selectors[port_selector]:
                    policy_group = port_selector_item['policy_group']
                    port_sr_name = port_selector_item['hport_name']
                    nodes = []
                    for sw_sel in port_to_switch_prof_map[port_selector]:
                        if sw_sel in switch_prof_leaves:
                            for node in switch_prof_leaves[sw_sel]:
                                nodes.append(node)

                    if nodes:
                        for node in set(nodes):
                            for intf in set(port_selector_item['interfaces']):
                                hport_dict = {}
                                key = int(node)*1000 + int(intf.split('/')[0])*100 + int(intf.split('/')[-1])
                                hport_dict['policy_group'] = policy_group
                                hport_dict['port_sr_name'] = port_sr_name
                                port_profiles[key] = hport_dict

        pods = self.md.lookupByClass('fabricPod', parentDn='topology')
        leaf_nodes = []
        for pod in pods:
            if target_node:
                nodes = self.md.lookupByClass('fabricNode', propFilter='eq(fabricNode.id, "{0}")'.format(target_node),
                                              parentDn=pod.dn)
            else:
                nodes = self.md.lookupByClass('fabricNode', parentDn=pod.dn)
            for node in nodes:
                if node.role == 'leaf':
                    leaf_nodes.append(node.rn)
            
            intfs = self.md.lookupByClass('l1PhysIf', parentDn='')
            if intfs:
                for intf in intfs:
                    node = str(intf.dn).split('/')[2]
                    if node in leaf_nodes:
                        intf_id = str(intf.id).strip('eth')
                        idx = int(str(node).split('-')[-1])*1000 + int(intf_id.split('/')[0])*100 +\
                            int(intf_id.split('/')[-1])
                        self.idict[idx] = {'node': str(node), 'intf_id': intf_id, 'portT': str(intf.portT),
                                           'usage': str(intf.usage), 'descr': str(intf.descr), 'operSt': '',
                                           'operSpeed': '', 'operDuplex': ''}

                phy_intfs = self.md.lookupByClass('ethpmPhysIf', parentDn='')
                 
                for phy_intf in phy_intfs:
                    node = str(phy_intf.dn).split('/')[2]
                    if node in leaf_nodes:
                        match = re.search('\[(eth\d+/\d+)\]', str(phy_intf.dn))
                        if match:
                            phy_intf_id = match.group(1).strip('eth')
                            search_idx = int(str(node).split('-')[-1])*1000 + int(phy_intf_id.split('/')[0])*100 +\
                                int(phy_intf_id.split('/')[-1])
                            if search_idx in self.idict:
                                self.idict[search_idx]['operSt'] = str(phy_intf.operSt)
                                self.idict[search_idx]['operSpeed'] = str(phy_intf.operSpeed)
                                self.idict[search_idx]['operDuplex'] = str(phy_intf.operDuplex)
    
        for key in self.idict:
            if key in port_profiles:
                self.idict[key]['port_sr_name'] = port_profiles[key]['port_sr_name']
                self.idict[key]['policy_group'] = port_profiles[key]['policy_group']
            else:
                self.idict[key]['port_sr_name'] = ''
                self.idict[key]['policy_group'] = ''
   
    def get_vlan_pool(self):

        result = self.refresh_connection()

        if result[0] == 1:
            return

        self.vlan_pools = []
        resp = self.md.lookupByClass('fvnsVlanInstP', '', subtree='children')
        for inst in resp:
            name = str(inst.name)
            alloc = str(inst.allocMode)
            domains = []
            if inst.numChildren > 0:
                for child in inst.children:
                    if 'RtVlanNs' in str(child.__class__):
                        domains.append(str(child.tDn).split('uni/')[1])
                for child in inst.children:
                    if 'EncapBlk' in str(child.__class__):
                        from_vlan = int(str(child.dn).split('from-[')[1].split(']')[0].replace('vlan-', ''))
                        to_vlan = int(str(child.to).replace('vlan-', ''))
                        self.vlan_pools.append({'name': name, 'alloc': alloc, 'domains': domains,
                                                'from_vlan': from_vlan, 'to_vlan': to_vlan})
 
    def vlan_usage(self, vlan):
        if self.vlan_pools:
            print 'VLAN:', vlan

            y = PrettyTable(
                ['POOL NAME', 'ALLOCATION', 'FROM', 'TO', 'DOMAINS'])
            y.align = "l"
            y.vertical_char = ' '
            y.junction_char = ' '

            for item in self.vlan_pools:
                if (int(vlan) >= item['from_vlan']) and (int(vlan) <= item['to_vlan']):
                    name = item['name']
                    alloc = item['alloc']
                    from_vlan = item['from_vlan']
                    to_vlan = item['to_vlan']
                    domains = str(item['domains'])[1:-2]
                    y.add_row([name, alloc, from_vlan, to_vlan, domains])
        print(y)

        if self.epgs:
            print '\n'
            y = PrettyTable(
                ['TENANT', 'APP_PROFILE', 'EPG', 'TAGS'])
            y.align = "l"
            y.vertical_char = ' '
            y.junction_char = ' '

            for epg in self.epgs:
                vlan_used = False
                for path in epg['paths']:
                    if str(vlan) == path['encap']:
                        vlan_used = True
                
                if vlan_used:
                    tenant = epg['tn']
                    ap_profile = epg['ap']
                    epg_name = epg['name']
                    tags = epg['tags']

                    y.add_row([tenant, ap_profile, epg_name, tags])
        print(y)
       
    def print_epgs(self):
        for epg in self.epgs:
            print '\n'
            print 'TN:', epg['tn']
            print 'AP:', epg['ap']
            print 'EPG:', epg['name']
            print 'TAG:', epg['tags']
            print 'BD:', epg['bd']

            y = PrettyTable(
                ['NODE', 'INTERFACE', 'VLAN', 'TOPOLOGY', 'USAGE', 'STATE', 'SPEED', 'PORT_SR_NAME',
                                  'POLICY_GROUP'])
            y.align = "l"
            y.vertical_char = ' '
            y.junction_char = ' '

            for path in epg['paths']:
                if 'vpc' in path:
                    for idx in self.idict:
                        if (path['vpc'] == self.idict[idx]['policy_group']) and (str(idx)[:3] in path['protpaths']):
                            node = self.idict[idx]['node'].replace('node-', '')
                            intf_id = self.idict[idx]['intf_id']
                            port_t = self.idict[idx]['portT']
                            usage = self.idict[idx]['usage']
                            oper_st = self.idict[idx]['operSt']
                            oper_speed = self.idict[idx]['operSpeed']
                            port_sr_name = self.idict[idx]['port_sr_name']
                            policy_group = self.idict[idx]['policy_group']
                            vlan = path['encap']
                            y.add_row([node, intf_id, vlan, port_t, usage, oper_st, oper_speed, port_sr_name,
                                       policy_group])

                elif path['idx'] in self.idict:
                    key = path['idx']
                    node = self.idict[key]['node'].replace('node-', '')
                    intf_id = self.idict[key]['intf_id']
                    port_t = self.idict[key]['portT']
                    usage = self.idict[key]['usage']
                    oper_st = self.idict[key]['operSt']
                    oper_speed = self.idict[key]['operSpeed']
                    port_sr_name = self.idict[key]['port_sr_name']
                    policy_group = self.idict[key]['policy_group']
                    vlan = path['encap']
                    y.add_row([node, intf_id, vlan, port_t, usage, oper_st, oper_speed, port_sr_name,
                               policy_group])

            print(y)

    def print_interface(self):
        print '* - flag indicates configured but not mapped to any EPG interfaces'

        y = PrettyTable(["F", "NODE", "INTERFACE", "TOPOLOGY", "USAGE", "STATE", "SPEED", "PORT_SR_NAME",
                         "POLICY_GROUP"])
        y.align = "l"
        y.vertical_char = ' '
        y.junction_char = ' '

        for key in sorted(self.idict):
            flag = ''
            node = self.idict[key]['node'].replace('node-', '')
            intf_id = self.idict[key]['intf_id']
            port_t = self.idict[key]['portT']
            usage = self.idict[key]['usage']
            oper_st = self.idict[key]['operSt']
            oper_speed = self.idict[key]['operSpeed']
            port_sr_name = self.idict[key]['port_sr_name']
            policy_group = self.idict[key]['policy_group']
            if ('discovery' in usage) and (port_sr_name or policy_group):
                flag = '*'
            y.add_row([flag, node, intf_id, port_t, usage, oper_st, oper_speed, port_sr_name, policy_group])
        print(y)

    def print_interface_details(self, key):
        print '* - flag indicates configured but not mapped to any EPG interfaces'

        y = PrettyTable(["F", "NODE", "INTERFACE", "TOPOLOGY", "USAGE", "STATE", "SPEED", "PORT_SR_NAME",
                         "POLICY_GROUP"])
        y.align = "l"
        y.vertical_char = ' '
        y.junction_char = ' '

        flag = ''
        node = self.idict[key]['node'].replace('node-', '')
        intf_id = self.idict[key]['intf_id']
        port_t = self.idict[key]['portT']
        usage = self.idict[key]['usage']
        oper_st = self.idict[key]['operSt']
        oper_speed = self.idict[key]['operSpeed']
        port_sr_name = self.idict[key]['port_sr_name']
        policy_group = self.idict[key]['policy_group']
        if ('discovery' in usage) and (port_sr_name or policy_group):
            flag = '*'
        y.add_row([flag, node, intf_id, port_t, usage, oper_st, oper_speed, port_sr_name, policy_group])
        print(y)

        print '\n EPG Binding Info: \n'

        y = PrettyTable(["TENANT", "APP PROFILE", "EPG", "BD", "VLAN_ENCAP"])
        y.align = "l"
        y.vertical_char = ' '
        y.junction_char = ' '

        for epg in self.epgs:
            for path in epg['paths']:
                if 'vpc' in path:
                    if (path['vpc'] == self.idict[key]['policy_group']) and (str(key)[:3] in path['protpaths']):
                        vlan = path['encap']
                        y.add_row([epg['tn'], epg['ap'], epg['name'], epg['bd'], vlan])

                elif path['idx'] == key:
                    vlan = path['encap']
                    y.add_row([epg['tn'], epg['ap'], epg['name'], epg['bd'], vlan])
        print (y)

    def print_vlan_pool(self):
        y = PrettyTable(["NAME", "ALLOCATION", "FROM", "TO", "DOMAINS"])
        y.align = "l"

        y.vertical_char = ' '
        y.junction_char = ' '
        for item in self.vlan_pools:
            name = item['name']
            alloc = item['alloc']
            from_vlan = item['from_vlan']
            to_vlan = item['to_vlan']
            domains = str(item['domains'])[1:-1]
            y.add_row([name, alloc, from_vlan, to_vlan, domains])
        print(y)

    def print_snapshot(self):
        self.collect_snapshots()
        y = PrettyTable(["ID", "TRIGGER", "TIME", "DESCRIPTION" ])
        y.align = "l"
        y.vertical_char = ' '
        y.junction_char = ' '


        snapshot_id = 0

        for snapshot in self.snapshots:
            trigger = ''
            dn = str(snapshot.dn)
            if 'OneTime' in dn:
                trigger = 'OneTime'
            elif 'DailyAuto' in dn:
                trigger = 'DailyAuto'
            elif 'defaultAuto' in dn:
                trigger = 'defaultAuto'

            snapshot_time = str(snapshot.createTime)
            descr = str(snapshot.descr)
            y.add_row([snapshot_id, trigger, snapshot_time, descr])
            snapshot_id += 1

        print(y)

 
if __name__ == '__main__':
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    requests.packages.urllib3.disable_warnings(InsecurePlatformWarning)
    requests.packages.urllib3.disable_warnings(SNIMissingWarning)
    try:
        apic = Apic()
        apic.prompt = 'ACLI()>'
        apic.cmdloop('Starting ACLI...')
    except KeyboardInterrupt:
        print "\nINFO: ACLI Shell was interrupted by Ctrl-C"
        apic.disconnect()

