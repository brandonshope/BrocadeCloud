#!/usr/bin/python
#
# VCloud Director - Autoscaling Driver and utility for Brocade vTM
#
# Name:     vclouddriver.py
# Version:  0.2
# Date:     2016-10-25
#  
# Copyright 2016 Brocade Communications Systems, Inc.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# Mark Boddington (mbodding@brocade.com), Brocade Communications Systems,Inc.

import sys
import os
import re
import requests
import time
import requests
import json
from requests.auth import HTTPBasicAuth
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import ElementTree


class VCloudManager(object):

    def __init__(self, api, org=None, vdc=None, verbose=False, timeout=60):

        NAME_SPACE = "http://www.vmware.com/vcloud/v1.5"
        XML_VERSION = "application/*+xml;version=5.1"

        if api.endswith('/') is False:
            api += "/"

        self.api = api
        self.ns = NAME_SPACE
        self.xmlVer = XML_VERSION
        self.org = org
        self.vdc = vdc
        self.headers = None
        self.config = None
        self.orgs = None
        self.vdcs = None
        self.vapps = {}
        self.vms = {}
        self.templates = {}
        self.dc_networks = {}
        self.vapp_networks = {}
        self.task = None
        self.timeout = timeout
        self.verbose = verbose
        self.customize = False
        self.terminate_on_shutdown = True
        self._setup_name_space()

    def _debug(self, msg):
        if self.verbose:
            sys.stderr.write("DEBUG: {}".format(msg))

    def _setup_name_space(self):
        ET.register_namespace("", self.ns)
        ET.register_namespace("ovf", "http://schemas.dmtf.org/ovf/envelope/1")
        ET.register_namespace("ovfenv", "http://schemas.dmtf.org/ovf/environment/1")
        ET.register_namespace("vmext", "http://www.vmware.com/vcloud/extension/v1.5")
        ET.register_namespace("cim", "http://schemas.dmtf.org/wbem/wscim/1/common")
        ET.register_namespace("rasd", "http://schemas.dmtf.org/wbem/wscim/1/" +
            "cim-schema/2/CIM_ResourceAllocationSettingData")
        ET.register_namespace("vssd", "http://schemas.dmtf.org/wbem/wscim/1/" +
            "/cim-schema/2/CIM_VirtualSystemSettingData")
        ET.register_namespace("vmw", "http://www.vmware.com/schema/ovf")
        ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    def _get_orgs(self):
        self.orgs = {}
        for org in self.config["Session"].findall(".//{" + self.ns + "}Link[@type=" +
            "'application/vnd.vmware.vcloud.org+xml']"):
            self.orgs[org.attrib.get("name")] = org.attrib.get("href")

    def _get_vdcs(self, org):
        self.vdcs = {}
        for vdc in self.config["ORG"][org].findall(".//{"+ self.ns + "}Link[@type=" +
            "'application/vnd.vmware.vcloud.vdc+xml']"):
            self.vdcs[vdc.attrib.get("name")] = vdc.attrib.get("href")

    def _get_vapps(self, vdc):
        for vapp in self.config["VDC"][vdc].findall(".//{"+ self.ns + "}ResourceEntity"):
            appType = vapp.attrib.get("type")
            if appType == 'application/vnd.vmware.vcloud.vApp+xml':
                self.vapps[vapp.attrib.get("name")] = vapp.attrib.get("href")
            elif appType == 'application/vnd.vmware.vcloud.vAppTemplate+xml':
                self.templates[vapp.attrib.get("name")] = vapp.attrib.get("href")

    def _get_networks(self, vdc):
        for net in self.config["VDC"][vdc].findall(".//{"+ self.ns + "}Network" +
            "[@type='application/vnd.vmware.vcloud.network+xml']"):
            self.dc_networks[net.attrib.get("name")] = net.attrib.get("href")

    def _get_vapp_networks(self, vapp):
        for net in self.config["VAPP"][vapp].findall(".//{" + self.ns + "}NetworkConfig"):
            link = net.find("./{" + self.ns +"}Link").attrib.get("href")
            link = link[:-13]
            self.vapp_networks[net.attrib.get("networkName")] = link

    def _get_virtual_machines(self, vapp):
        for v in self.config["VAPP"][vapp].findall(".//{"+ self.ns +"}Vm"):
            self.vms[v.attrib.get("name")] = v.attrib.get("href")

    def _check_args(self, org, vdc):
        if self.config is None:
            raise Exception("ERROR: You must call setupSession() first!")
        if org is None:
            if self.org is None:
                raise Exception("ERROR: You didn't provide a default ORG to VCloudManager(), so you must provide one here")
            else:
                org = self.org
        if vdc is None:
            if self.vdc is None:
                raise Exception("ERROR: You didn't provide a default VDC to VCloudManager(), so you must provide one here")
            else:
                vdc = self.vdc
        return [ org, vdc ]

    def _do_get_config(self, name, dictionary, append=""):
        if name not in dictionary:
            raise Exception("ERROR: Could not locate configuration for: {}.".format(name))
        self._debug("HTTP GET for: {}, Calling: {}\n".format(name, dictionary[name] + append))
        response = requests.get(dictionary[name] + append, headers=self.headers)
        if response.status_code != 200:
            raise Exception("HTTP Request Failed: {}".format(response.status_code))
        return ET.fromstring(response.text)

    def setup_session(self, user, password):
        url = self.api + "sessions"
        auth = HTTPBasicAuth(user, password)
        self.headers = {"Accept": self.xmlVer}
        response = requests.post(url, headers=self.headers, auth=auth)
        if response.status_code != 200:
            raise Exception("Authentication Failed: {}".format(response.status_code))
        self.headers['x-vcloud-authorization'] = response.headers['x-vcloud-authorization']
        self.config = { "Session": ET.fromstring(response.text), "ORG": {}, "NET": {},
            "VDC": {}, "VAPP": {}, "TMPL": {}, "VMS": {}, "META": {} }

    def enable_customization(self, customize):
        self.customize = customize

    def close_session(self):
        self.headers = None
        self.config = None

    def list_orgs(self):
        self._check_args("", "")
        self._get_orgs()
        return self.orgs

    def get_org_config(self, org=None):
        org, vdc = self._check_args(org, "")
        self._get_orgs()
        self.config["ORG"][org] = self._do_get_config(org, self.orgs)
        return self.config["ORG"][org]

    def list_vdcs(self, org=None):
        org, vdc = self._check_args(org, "")
        if org not in self.config["ORG"].keys():
            self.get_org_config(org)
        self._get_vdcs(org)
        return self.vdcs

    def get_vdc_config(self, org=None, vdc=None):
        org, vdc = self._check_args(org, vdc)
        if org not in self.config["ORG"].keys():
            self.get_org_config(org)
        self._get_vdcs(org)
        self.config["VDC"][vdc] = self._do_get_config(vdc, self.vdcs)
        return self.config["VDC"][vdc]

    def list_vapps(self, org=None, vdc=None):
        org, vdc = self._check_args(org, vdc)
        if vdc not in self.config["VDC"].keys():
            self.get_vdc_config(org, vdc)
        self._get_vapps(vdc)
        return self.vapps

    def list_vapp_templates(self, org=None, vdc=None):
        self.list_vapps(org, vdc)
        return self.templates

    def get_vapp_config(self, vapp, org=None, vdc=None):
        self.list_vapps(org, vdc)
        self.config["VAPP"][vapp] = self._do_get_config(vapp, self.vapps)
        return self.config["VAPP"][vapp]

    def get_vapp_metadata(self, vapp, key=None, org=None, vdc=None):
        self.list_vapps(org, vdc)
        self.config["META"][vapp] = self._do_get_config(vapp, self.vapps, "/metadata")
        if key is None:
            return self.config["META"][vapp]
        else:
            return self._get_metadata_entry(self.config["META"][vapp], key)

    def add_vapp_metadata(self, vapp, dictionary, org=None, vdc=None):
        self.list_vapps(org, vdc)
        if vapp not in self.vapps:
            raise Exception("Error: No such VApp: {}".format(vapp))
        uri = self.vapps[vapp] + "/metadata"
        metadata = self._build_metadata(dictionary)
        success = self.submit_task(uri, name="Set Metadata", 
            ct="application/vnd.vmware.vcloud.metadata+xml",
            data=ET.tostring(metadata))
        return success

    def get_vapp_template_config(self, vapp, org=None, vdc=None):
        self.list_vapps(org, vdc)
        self.config["TMPL"][vapp] = self._do_get_config(vapp, self.templates)
        return self.config["TMPL"][vapp]

    def list_vapp_vms(self, vapp, org=None, vdc=None):
        org, vdc = self._check_args(org, vdc)
        if vapp not in self.config["VAPP"].keys():
            self.get_vapp_config(vapp, org, vdc)
        self._get_virtual_machines(vapp)
        return self.vms

    def get_vapp_vm_config(self, vapp, vm, org=None, vdc=None):
        self.list_vapp_vms(vapp, org, vdc)
        self.config["VMS"][vm] = self._do_get_config(vm,self.vms)
        return self.config["VMS"][vm]

    def get_vapp_vm_metadata(self, vapp, vm, key=None, org=None, vdc=None):
        self.list_vapp_vms(vapp, org, vdc)
        self.config["META"][vm] = self._do_get_config(vm, self.vms, "/metadata")
        if key is None:
            return self.config["META"][vm]
        else:
            return self._get_metadata_entry(self.config["META"][vm], key)

    def add_vapp_vm_metadata(self, vapp, vm, dictionary, org=None, vdc=None):
        self.list_vapp_vms(vapp, org, vdc)
        if vm not in self.vms:
            raise Exception("Error: No such VM: {}".format(vm))
        uri = self.vms[vm] + "/metadata"
        metadata = self._build_metadata(dictionary)
        success = self.submit_task(uri, name="Set Metadata", 
            ct="application/vnd.vmware.vcloud.metadata+xml",
            data=ET.tostring(metadata))
        return success

    def _build_metadata(self, dictionary):
        metadata = Element("{" + self.ns + "}Metadata")
        for key in dictionary.keys():
            value = dictionary[key]["value"]
            if "type" in dictionary[key].keys():
                mdType = dictionary[key]["type"]
            else:
                mdType = None
            self._add_metadata_entry(metadata, key, value, mdType)
        return metadata

    def _add_metadata_entry(self, md, key, value, mdType="MetadataStringValue"):
        xsi = "http://www.w3.org/2001/XMLSchema-instance"
        mde = Element("MetadataEntry")
        mKey = Element("Key")
        mKey.text = key
        mde.append(mKey)
        mVal = Element("Value")
        mVal.text = value
        if mdType is not None:
            typedVal = Element("TypedValue")
            typedVal.set("{" + xsi + "}type", mdType) 
            typedVal.append(mVal)
            mde.append(typedVal)
        else:
            mde.append(mVal)
        md.append(mde)

    def _get_metadata_entry(self, md, key):
        kvps = md.findall("{" + self.ns + "}MetadataEntry")
        for kvp in kvps:
            entry = kvp.find("{" + self.ns + "}Key")
            if entry is not None and entry.text == key:
                value = kvp.find(".//{" + self.ns + "}Value")
                if value is not None:
                    return value.text
        return None

    def set_vapp_vm_creation_time(self, vapp, vm, org=None, vdc=None):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status = self.add_vapp_vm_metadata(vapp, vm, "created", stamp, "MetadataDateTimeValue")
        return status

    def get_vapp_vm_creation_time(self, vapp, vm, org=None, vdc=None):
        md = self.get_vapp_vm_metadata(vapp, vm, org, vdc)
        epoc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(0))
        value = self._get_metadata_entry(md, "created")
        value = epoc if value is None else value
        return value 

    def list_networks(self, org=None, vdc=None):
        org, vdc = self._check_args(org, vdc)
        if vdc not in self.config["VDC"].keys():
            self.get_vdc_config(org,vdc)
        self._get_networks(vdc)
        return self.dc_networks

    def get_network_config(self, network, org=None, vdc=None):
        self.list_networks(org, vdc)
        self.config["NET"][network] = self._do_get_config(network, self.dc_networks)
        return self.config["NET"][network]

    def list_vapp_networks(self, vapp, org=None, vdc=None):
        org, vdc = self._check_args(org, vdc)
        if vapp not in self.config["VAPP"].keys():
            self.get_vapp_config(vapp, org, vdc)
        self._get_vapp_networks(vapp)
        return self.vapp_networks 

    def get_vapp_network_config(self, vapp, network, org=None, vdc=None):
        self.list_vapp_networks(vapp)
        self.config["NET"][network] = self._do_get_config(network, self.vapp_networks)
        return self.config["NET"][network]

    def get_vm_status(self, vapp, vm=None):
        vms = self.list_vapp_vms(vapp) if vm is None else [ vm ]
        status = {}
        for vm in vms:
            config = self.get_vapp_vm_config(vapp, vm)
            status[vm] = {"status": config.attrib.get("status"),
                          "id": config.attrib.get("id"),
                          "name": config.attrib.get("name"),
                          "needsCustomization": config.attrib.get("needsCustomization"),
                          "deployed": config.attrib.get("deployed"),
                          "nets": {}}
            net_conns = config.findall('.//{' + self.ns + '}NetworkConnection')
            for net in net_conns:
                network = net.attrib.get("network")
                ip = net.find('.//{' + self.ns + '}IpAddress')
                if ip is None:
                    status[vm]["nets"][network] = ""
                else:
                    status[vm]["nets"][network] = ip.text
        return status

    def get_task_status(self, task):
        uri = task.get("href")
        response = requests.get(uri, headers=self.headers)
        if response.status_code != 200:
            self._debug("CODE: {}\n".format(response.status_code))
            self._debug("DATA: {}\n".format(response.text))
            raise Exception("Failed to get task. Code: {},".format(response.status_code) +
                " Data: {}".format(response.text))
        return ET.fromstring(response.text)

    def wait_for_task(self, task):
        start = time.time()
        status = task.get("status")
        while status == "running":
            self._debug("waiting for task: {:0>2.2f}\n".format(time.time() - start))
            if time.time() - start > self.timeout:
                return "running"
            time.sleep(5)
            task = self.get_task_status(task)
            status = task.get("status")
        return status

    def submit_task(self, uri, name="Task", ct=None, data=None):
        headers = self.headers
        if ct is not None:
            headers["Content-Type"] = ct
        response = requests.post(uri, headers=headers, data=data)
        self._debug("POST: {}\n".format(uri))
        self._debug("Headers: {}\n".format(headers))
        self._debug("DATA: {}\n".format(data))
        self._debug("{} Task Submitted.\n".format(name))
        if response.status_code != 202:
            raise Exception("ERROR: Task submission failed. Code: {},".format(response.status_code) +
                " Data: {}".format(response.text))
        self._debug("{} Running.\n".format(name))
        task = ET.fromstring(response.text)
        status = self.wait_for_task(task)
        self._debug("{} Task Complete. Status: {}\n".format(name, status))
        return status

    def add_vm_to_vapp(self, vapp, template, networks, ipMode, vm):
        if template not in self.templates.keys():
            raise Exception("Template has not been discovered: {}".format(template))
        for network in networks:
            if network not in self.vapp_networks.keys():
                raise Exception("Network has not been discovered: {}".format(network))
        rvo = RecomposeVAppObject(self.ns, self.customize)
        rvo.add_vm_to_vapp(networks, self.vapp_networks, ipMode, vm, template, self.config)
        xml = rvo.to_string()
        uri = self.vapps[vapp] + "/action/recomposeVApp"
        ct = "application/vnd.vmware.vcloud.recomposeVAppParams+xml"
        status = self.submit_task(uri, "Recompose VAPP", ct, xml)
        if status == "success":
            self.get_vapp_config(vapp)
            self.list_vapp_vms(vapp)
        return status

    def del_vm_from_vapp(self, vapp, vm):
        if self.vms is None or vm not in self.vms:
            self.get_vapp_vm_config(vapp, vm)
        if vm not in self.vms:
            raise Exception("Unknown VM: {}".format(vm))

        self.shutdown(vm)
        rvo = RecomposeVAppObject(self.ns)
        rvo.del_vm_from_vapp(self.vms[vm])
        xml = rvo.to_string()
        uri = self.vapps[vapp] + "/action/recomposeVApp"
        ct = "application/vnd.vmware.vcloud.recomposeVAppParams+xml"
        status = self.submit_task(uri, "Recompose VAPP", ct, xml)
        return status
        
    def poweron(self, vm):
        if vm not in self.vms:
            raise Exception("ERROR: Unknown VM: {}".format(vm))
        uri = self.vms[vm] + "/power/action/powerOn"
        status = self.submit_task(uri, "Power On")
        return status

    def shutdown(self, vm):
        if vm not in self.vms:
            raise Exception("ERROR: Unknown VM: {}".format(vm))
        uri = self.vms[vm] + "/action/undeploy"
        ct = "application/vnd.vmware.vcloud.undeployVAppParams+xml"
        upa = Element("UndeployPowerAction")
        if self.terminate_on_shutdown:
            upa.text = "powerOff"
        else:
            upa.text = "shutdown"
        uvp = Element("{"+ self.ns + "}UndeployVAppParams")
        uvp.append(upa)
        xml = ET.tostring(uvp)
        try:
            status = self.submit_task(uri, "Power Off", ct, xml)
        except Exception as e:
            if "is not running" in str(e):
                self._debug("VM Appears to be powered off already, continuing....\n")
                return "success"
            else:
                raise e
        return status


class RecomposeVAppObject(object):

    def __init__(self, ns, customize=False, text="Recompose VApp"):

        self._root = Element("RecomposeVAppParams")
        self.ns = ns
        self.ovf = "http://schemas.dmtf.org/ovf/envelope/1"
        self.customize = customize
        desc = Element("Description")
        desc.text = text
        self._root.append(desc)

    def add_vm_to_vapp(self, netNames, netLinks, ipMode, vmName, template, config):
        if template not in config["TMPL"].keys():
            raise Exception("Template has not been discovered: {}".format(template))

        if ipMode not in [ "POOL", "DHCP" ]:
            raise Exception("IP Address Allocation 'ipMode' should be one of 'POOL' or 'DHCP'")

        # Configure the Template
        sourcedItem = Element("{" + self.ns + "}SourcedItem")
        vm = config["TMPL"][template].find(".//{" + self.ns + "}Vm")
        source = Element("Source", href=vm.attrib.get("href"), name=vmName)
        instParams = Element("InstantiationParams")
        netConnSec = Element("NetworkConnectionSection")
        netConnInf = Element("{" + self.ovf + "}Info")
        netConnInf.text = "Specifies the available VM network connections"
        netConnSec.append(netConnInf)
        for i in xrange(len(netNames)):
            netConn = Element("NetworkConnection", network=netNames[i], needsCustomization="true")
            nci = Element("NetworkConnectionIndex")
            nci.text = str(i)
            ipAddr = Element("IpAddress")
            connected = Element("IsConnected")
            connected.text = "true"
            macAddr = Element("MACAddress")
            allocation = Element("IpAddressAllocationMode")
            allocation.text = ipMode
            netConn.append(nci)
            netConn.append(ipAddr)
            netConn.append(connected)
            netConn.append(macAddr)
            netConn.append(allocation)
            netConnSec.append(netConn)   
        instParams.append(netConnSec)
        sourcedItem.append(source)
        if self.customize:
            vgp = Element("VmGeneralParams")
            nc = Element("NeedsCustomization")
            nc.text = "true"
            vgp.append(nc)
            sourcedItem.append(vgp)
        sourcedItem.append(instParams)
        self._root.append(sourcedItem)

    def del_vm_from_vapp(self, nodeLink):
        delItem = Element("{" + self.ns + "}DeleteItem", href=nodeLink)
        self._root.append(delItem)

    def to_string(self, encoding="utf-8", method="xml"):
        return ET.tostring(self._root, encoding, method)
        
# Script Functions

def help():
    text="""
    Usage: vclouddriver.py [--help] action options

        action: [status|createnode|destroynode|get-vdc-info]

        common options:
            --verbose          Print verbose logging messages to the CLI
            --cloudcreds=<CC>  vTM Cloud Credential name. The script will try
                               to locate this file under $ZEUSHOME.
                               Only cred1 is used, and should point to your
                               VApp configuration file.

        When running manually, you can pass the VApp config file directly: 

            --cred1=<VApp configfile>

        Configuration file:
        -------------------

        The config file should include: apiHost, user, pass, org, vdc, vapp,
        and network. You may also override these by passing them on the
        command line. Eg: --apiHost, --vdc, --vapp, etc

        action-specific options:
        ------------------------

        createnode                Add a node to the cloud

            --name=<nodename>     Name to give the new node
            --imageid=<template>  The template to use 
            --sizeid=<size>       Not used

        destroynode               Remove a node from the cloud

            --id=<uniqueid>       ID of the node to delete
            --name=<nodename>     Name of the node to delete

        status                    Get current node status 

            --name=<nodename>     Display the status of the named node only

        get-vdc-info              Display a list of resource in your VDC

            --wrap                Wrap output to match the console width

"""
    sys.stderr.write(text)
    sys.exit(1)

def convertNodeData(opts,vcm,item):
    networks = get_net_list(opts)
    node = { "uniq_id": item['id'], "name": item["name"], "sizeid": opts["sizeid"] }

    if len(networks) == 1:
        node["public_ip"] = item["nets"][networks[0]]
        node["private_ip"] = item["nets"][networks[0]]
    else:
        if "pubNet" in opts.keys() and opts["pubNet"] in item["nets"].keys():
            node["public_ip"] = item["nets"][opts["pubNet"]]

        if "privNet" in opts.keys() and opts["privNet"] in item["nets"].keys():
            node["private_ip"] = item["nets"][opts["privNet"]]

        if "public_ip" not in node.keys():
            node["public_ip"] = item["nets"][networks[0]]

        if "private_ip" not in node.keys():
            node["private_ip"] = item["nets"][networks[1]]

    status = int(item["status"])
    if status < 4:
        node["status"] = "pending"
        node["complete"] = 33
    elif status == 4:
        if node["public_ip"] == "" or node["private_ip"] == "":
            node["status"] = "pending"
            node["complete"] = 66
        elif item["deployed"] == "true":
            node["status"] = "active"
            node["complete"] = 100
        else:
            node["status"] = "pending"
            node["complete"] = 66
    else:
        if item["deployed"] == "true":
            node["satus"] = "pending"
            node["complete"] = 66
        else:
            node["status"] = "destroyed"
            node["complete"] = 100
    return node

def get_delta(vcm, opts, nodes):

    now = int(time.time())
    history = vcm.get_vapp_metadata(opts["vapp"], "vtm_history")

    if history is None:
        history = { now: nodes }
        metadata = { "vtm_history": { "value": json.dumps(history), "type": "MetadataStringValue" } }
        vcm.add_vapp_metadata(opts["vapp"], metadata)
        return nodes

    history = json.loads(history)
    deltasince = int( opts["deltasince"] ) + 10
    entries = sorted(history.keys())
    entry = max([entry for entry in entries if int(entry) <= deltasince or entry == entries[0]])
    oldNodes = {node["name"]:node for node in history[entry]}
    current = {node["name"]:node for node in nodes}

    delta = []
    for node in oldNodes.keys():
        if node in current.keys():
            if current[node] != oldNodes[node]:
                delta.append(current[node])
        else:
            oldNodes[node]["status"] = "destroyed"
            oldNodes[node]["complete"] = 100
            delta.append(oldNodes[node])

    while len(entries) >= 2:
        del history[entries.pop(0)]

    history[now] = nodes
    metadata = { "vtm_history": { "value": json.dumps(history), "type": "MetadataStringValue" } }
    vcm.add_vapp_metadata(opts["vapp"], metadata)
    return delta

def get_status(opts, vcm):
    nodes = []
    if "name" in opts.keys():
        status = vcm.get_vm_status(opts["vapp"], opts["name"])
    else:
        status = vcm.get_vm_status(opts["vapp"])

    for vm in status.keys():
        node = status[vm]
        node = convertNodeData(opts,vcm,node)
        node["created"] = vcm.get_vapp_vm_creation_time(opts["vapp"], vm)
        nodes.append(node)

    if "deltasince" in opts.keys():
        nodes = get_delta(vcm, opts, nodes)

    return nodes

def get_net_list(opts):
    networks = []
    if "pubNet" in opts.keys():
        networks.append(opts['pubNet'])
    if "privNet" in opts.keys():
        networks.append(opts['privNet'])
    if "networks" in opts.keys():
        networks += opts['networks'].split(',')
    if len(networks) == 0:
        sys.stderr.write("ERROR - You must provide atleast one of 'networks', " +
            "'pubNet' or 'privNet' in your configfile: {}\n".format(opts['cred1']))
        sys.exit(1)
    return [net.strip() for net in networks]

def add_node(opts, vcm):
    if "name" not in opts.keys() or "imageid" not in opts.keys():
        sys.stderr.write("ERROR - You must provide --name, and --imageid to create a node\n")
        sys.exit(1)

    vcm.get_vapp_template_config(opts["imageid"])
    networks = get_net_list(opts)
    vcm.list_vapp_networks(opts['vapp'])
    status = vcm.add_vm_to_vapp(opts["vapp"], opts["imageid"], networks, opts["ipMode"], opts["name"])
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    metadata = { "created": { "value": stamp, "type": "MetadataDateTimeValue" }}
    status = vcm.add_vapp_vm_metadata(opts["vapp"], opts["name"], metadata)
    status = vcm.poweron(opts["name"])
    nodeStatus = vcm.get_vm_status(opts["vapp"], opts["name"])
    myNode = convertNodeData(opts, vcm, nodeStatus[opts["name"]])
    myNode["created"] = stamp
    ret = { "CreateNodeResponse":{"version":1, "code":202, "nodes":[ myNode ]}}
    print json.dumps(ret)

def del_node(opts, vcm):
    if "name" not in opts.keys() and "id" not in opts.keys():
        sys.stderr.write("ERROR - please provide --name or --id to delete node\n")
        sys.exit(1)

    myNode = None
    nodes = get_status(opts, vcm)
    for node in nodes:
        if "name" in opts.keys() and node["name"] == opts["name"]:
            myNode = node
            break
        elif "id" in opts.keys() and node["uniq_id"] == opts["id"]:
            myNode = node
            break

    if myNode is not None:
        vcm.del_vm_from_vapp(opts["vapp"], myNode["name"])
        ret = { "DestroyNodeResponse": { "version": 1, "code": 202, "nodes": \
            [{ "created": 0, "uniq_id": myNode['uniq_id'], "status": "destroyed", \
            "complete": "80"}]}}
    else:
        # should probbaly return a 404???
        opts["id"] = None if "id" not in opts.keys() else opts["id"]
        ret = { "DestroyNodeResponse": { "version": 1, "code": 202, "nodes": \
            [{ "created": 0, "uniq_id": opts['id'], "status": "destroyed", \
            "complete": "80"}]}}

    print json.dumps(ret)

def print_table(dictionary, wrap=False, spacing=3):
    kl = 0
    vl = 0
    if wrap:
        columns = int(os.popen('stty size', 'r').read().split()[1])
    for key in dictionary.keys():
        for item in dictionary[key].keys():
            kl = len(item) if len(item) > kl else kl
            vl = len(dictionary[key][item]) if len(dictionary[key][item]) > vl else vl
    if wrap and kl+spacing >= columns:
        print "ABORTING WRAP: Columns less than Key Size"
        wrap = False
    for key in dictionary.keys():
        tl = kl+vl+spacing
        if wrap:
            tl = columns if tl > columns else tl
        print "\n{}\n\n{}\n{}".format("_"*tl, key, "~"*tl)
        for item in dictionary[key].keys():
            sp = kl - len(item) + spacing
            line = "{}{}{}".format(item, " "*sp, dictionary[key][item])
            if wrap:
                print line[:columns]
                line = line[columns:]
                while line:
                    tab=kl+spacing
                    print "{}{}".format(" "*tab, line[:columns-tab])
                    line = line[columns-tab:]
            else:
                print line

        print "{}".format("~"*tl)

def get_vdc_info(opts, vcm):
    to_print = {}
    to_print["Organizations"] = vcm.list_orgs()
    to_print["Virtual DCs"] = vcm.list_vdcs()
    to_print["Virtual DC Networks"] = vcm.list_networks()
    to_print["Virtual Apps"] = vcm.list_vapps()
    to_print["Virtual App Networks: {}".format(opts['vapp'])] = vcm.list_vapp_networks(opts["vapp"])
    to_print["Virtual AppTemplates"] = vcm.list_vapp_templates()

    wrap = False
    if "wrap" in opts.keys():
        wrap = True
    print_table(to_print, wrap)

def get_cloud_credentials(opts):

    # Find ZeusHome
    opts["ZH"] = os.environ.get("ZEUSHOME")
    if opts["ZH"] == None:
        if os.path.isdir("/usr/local/zeus"):
            opts["ZH"] = "/usr/local/zeus";
        elif os.path.isdir("/opt/zeus"):
            opts["ZH"] = "/opt/zeus";
        else:
            sys.stderr.write("ERROR - Can not find ZEUSHOME\n")
            sys.exit(1)

    # Open and parse the credentials file
    ccFile = opts["ZH"] + "/zxtm/conf/cloudcredentials/" + opts["cloudcreds"]
    if os.path.exists(ccFile) is False:
        sys.stderr.write("ERROR - Cloud credentials file does not exist: " + ccFile + "\n")
        sys.exit(1)
    ccFH = open( ccFile, "r")
    for line in ccFH:
        kvp = re.search("(\w+)\s+(.*)", line.strip() )
        if kvp != None:
            opts[kvp.group(1)] = kvp.group(2)
    ccFH.close()

    # Check credential 1 is the config file
    if "cred1" in opts.keys():
        opts["cred1"] = opts["ZH"] + "/zxtm/conf/extra/" + opts["cred1"]
        if os.path.exists( opts["cred1"] ) is False:
            sys.stderr.write("ERROR - VCloud config file is missing: " + opts["cred1"] + "\n")
            sys.exit(1)
    else:
        sys.stderr.write("ERROR - Credential 1 must be set to the VCloud config file name\n")
        sys.exit(1)

def setup(opts):

    if "cred1" not in opts.keys():
        get_cloud_credentials(opts)

    osFH = open( opts["cred1"], "r")
    for line in osFH:
        kvp = re.search("(\w+)\s+(.*)", line.strip() )
        if kvp != None:
            # command line args take precedence
            if kvp.group(1) not in opts.keys():
                opts[kvp.group(1)] = kvp.group(2)
    osFH.close()

    if "apiHost" not in opts.keys():
        sys.stderr.write("ERROR - 'apiHost' must be specified in the VCD config file: " + opts["cred1"] + "\n")
        sys.exit(1)

    if "org" not in opts.keys():
        sys.stderr.write("ERROR - 'org' must be specified in the VCD config file: " + opts["cred1"] + "\n")
        sys.exit(1)

    if "vdc" not in opts.keys():
        sys.stderr.write("ERROR - 'vdc' must be specified in the VCD config file: " + opts["cred1"] + "\n")
        sys.exit(1)

    if "sizeid" not in opts.keys():
        sys.stderr.write("ERROR - 'sizeid' must be specified in the VCD config file: " + opts["cred1"] + "\n")
        sys.exit(1)

    # Store state in zxtm/internal if being run by vTM
    if "statefile" not in opts.keys():
        if "ZH" in opts.keys():
            opts["statefile"] = opts["ZH"] + "/zxtm/internal/vcd." + \
                opts["cloudcreds"] + ".state"
        else:
            opts["statefile"] = None

    # Set up the VCloudManager
    vcm = VCloudManager(opts["apiHost"], opts["org"], opts["vdc"], opts["verbose"])
    vcm.setup_session(opts["user"], opts["pass"])
    vcm.get_vapp_config(opts["vapp"])

    if "customize" in opts.keys():
        if opts["customize"].lower() == "true":
            vcm.enable_customization(True)
        else:
            vcm.enable_customization(False)

    return vcm

def main():
    opts = {}

    # Read in the first argument or display the help
    if len(sys.argv) < 2:
        help()
    else:
        action = sys.argv[1]

    # Process additional arguments
    for arg in sys.argv:
        kvp = re.search("--([^=]+)=*(.*)", arg)
        if kvp != None:
            opts[kvp.group(1)] = kvp.group(2)

    if "verbose" in opts.keys():
        opts["verbose"] = True
    else:
        opts["verbose"] = False

    # Check the action and call the appropriate function
    if action.lower() == "help":
        help()
    elif action.lower() == "status":
        vcm = setup(opts)
        nodes = get_status(opts, vcm)
        print json.dumps({ "NodeStatusResponse":{ "version": 1, "code": 200, "nodes": nodes }})
    elif action.lower() == "createnode":
        vcm = setup(opts)
        add_node(opts, vcm)
    elif action.lower() == "destroynode":
        vcm = setup(opts)
        del_node(opts, vcm)
    elif action.lower() == "get-vdc-info":
        vcm = setup(opts)
        get_vdc_info(opts, vcm)
    else:
        help()

if __name__ == "__main__":
    main()
