# -*- encoding: utf-8 -*-
import xml.etree.cElementTree as ET
from pkg_resources import parse_version
import urllib
import win32evtlog
import win32evtlogutil
import win32security
import win32con
import winerror
import winreg
# Imports WPKGCOnnection:
from win32pipe import *
from win32file import *
import pywintypes
import win32api
import re
import string
import traceback
import datetime
from dateutil.parser import *
import os
import sys
from subprocess import Popen, PIPE, call, check_output

msi_exit_dic = {"1619": "ERROR_INSTALL_PACKAGE_OPEN_FAILED",
                "1612": "ERROR_INSTALL_SOURCE_ABSENT"}

def get_client_path():
    # Get Executable Path:
    pathname = os.path.dirname(sys.argv[0])
    path = os.path.abspath(pathname) + os.sep
    return path

def wpkg_running():
    running = None
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, R"SOFTWARE\WPKG", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        running = winreg.QueryValueEx(key, "running")[0]
        winreg.CloseKey(key)
    except WindowsError:
        pass
    if running == 'true':
        return True
    else:
        return False

def wpkggp_version(version):
    req_version = version
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, R"SOFTWARE\Wpkg-Gp", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        inst_version = winreg.QueryValueEx(key, "DisplayVersion")[0]
        winreg.CloseKey(key)
    except WindowsError:
        inst_version = None
        return False
    if parse_version(req_version) <= parse_version(inst_version):
        return True
    else:
        return False

def arch_check():
    # Detect if x86 or AMD64 and set correct path to wpkg.xml
    # The Environment Variable PROCESSOR_ARCHITEW6432 only exists on 64bit Windows
    if os.environ.get("PROCESSOR_ARCHITEW6432"):
        if os.environ['PROCESSOR_ARCHITECTURE'] == "AMD64":
            # 64bit python on x64
            sys_folder = "System32"
        else:
            # 32bit python on x64
            sys_folder = "Sysnative"
            # Sysnative is needed to access the true System32 folder from a 32bit application
        arch = "x64"
    else:
        sys_folder = "System32"
        arch = "x86"
    xml_file = os.path.join(os.getenv('systemroot'), sys_folder, "wpkg.xml")
    return xml_file, arch

def get_help_translation(path, language):
    # get first two characters of language string
    help_lang = language[:2]
    help_folder_path = os.path.join(path, 'help')
    # generate possible helpfile path
    help_file_path = os.path.join(help_folder_path, 'help_{}.md'.format(help_lang) )
    # if help file exists return the relative path, if not return path for english helpfile
    if os.path.isfile(help_file_path):
        return os.path.relpath(help_file_path, path)
    else:
        return 'help\help_en.md'

def client_running():
    # Use psutils library instead?
    n = 0
    prog=[line.split() for line in check_output("tasklist", creationflags=0x08000000).splitlines()]
    [prog.pop(0) for _ in [0,1,2,3]] #clean up output and remove unwanted lines
    clienttasklist = []
    sessionid = None
    for entry in prog:
        if 'WPKG-GP-Client.exe' == entry[0].decode():
            #store all instances of the client and its session id
            if len(entry) == 5:
                clienttasklist.append((entry[0], entry[2]))
            else:
                clienttasklist.append((entry[0], entry[3]))
        if 'tasklist.exe' == entry[0]:
            # setting sessionid of this session
            sessionid = entry[3]
        else:
            continue
    for entry in clienttasklist:
        if entry[1] == sessionid:
            # if session id is the same of this session count it as instance
            n += 1
        else:
            continue
    if n > 1:
        return True
    else:
        return False

def shutdown(mode, time=60, msg=None):
    time = str(time)
    shutdown_base_str = u"shutdown.exe "
    if mode == 1:
        shutdown_str = shutdown_base_str + "/f /r /t {}".format(time)
    elif mode == 2:
        shutdown_str = shutdown_base_str + "/f /s /t {}".format(time)
    elif mode == 3:
        shutdown_str = shutdown_base_str + "/a"
    else:
        print('mode needs to be 1 = reboot, 2 = shutdown or 3 = cancel')
        return
    if mode < 3:
        if msg:
            if "%TIME%" in msg:
                msg = msg.replace("%TIME%", str(time))
                print(msg) # DEBGUG
            shutdown_str += u' /c "{}"'.format(UNICODE(msg))
    # Don't Display Console Window
    # Source: http://stackoverflow.com/questions/7006238/how-do-i-hide-the-console-when-i-use-os-system-or-subprocess-call
    CREATE_NO_WINDOW = 0x08000000
    call(shutdown_str.encode(sys.getfilesystemencoding()), creationflags=CREATE_NO_WINDOW)

def SetRebootPendingTime(reset=False):
    if reset:
        now = "None"
    else:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, R"SOFTWARE\Wpkg-GP-Client", 0,
                             winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as key:
        winreg.SetValueEx(key, "RebootPending", 0, winreg.REG_EXPAND_SZ, now)

def ReadRebootPendingTime():
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, R"SOFTWARE\Wpkg-GP-Client", 0,
                             winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as key:
        try:
            reboot_pending_value = winreg.QueryValueEx(key, "RebootPending")[0]
        except WindowsError:
            return None
    try:
        reboot_pending_time = parse(reboot_pending_value)
    except (ValueError, TypeError):
        return None
    return reboot_pending_time

def ReadLastSyncTime():
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, R"SOFTWARE\WPKG", 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        try:
            last_sync_value = winreg.QueryValueEx(key, "lastsync")[0]
        except WindowsError:
            return None
    try:
        last_sync_time = parse(last_sync_value)
    except (ValueError, TypeError):
        return None
    return last_sync_time

def vpn_connected(arch="x64"):
    if arch == "x64":
        vpn_path = "C:\Program Files (x86)\Cisco\Cisco AnyConnect Secure Mobility Client\\vpncli.exe"
    else:
        vpn_path = "C:\Program Files\Cisco\Cisco AnyConnect Secure Mobility Client\\vpncli.exe"
    p = Popen('"{}" -s state'.format(vpn_path), stdout=PIPE, stderr=PIPE, shell=True)
    out, err = p.communicate()
    if err:
        print(err) # TODO: DEBUG
        return False
    else:
        if ">> notice: Connected to" in out:
            return True
        else:
            return False

def getPercentage(str):
    pat = re.compile('\(([0-9]{1,3})\/([0-9]{1,3})\)')
    try:
        cur, max = re.search(pat, str).groups()
    except AttributeError as e:
        #print e
        progress = 1
    else:
        try:
            progress = (float(cur) / float(max)) * 100
        except ZeroDivisionError:
            progress = 1
    if progress == 100:
        return 99
    else:
        return int(progress)

def getBootUp():
    p = Popen('wmic os get lastbootuptime', stdout=PIPE, stderr=PIPE, shell=True)
    out, err = p.communicate()
    outS = out.decode('UTF-8')
    part_out = (outS.split("\n", 1)[1]).split(".", 1)[0]
    bootup_time = parse(part_out)
    return bootup_time

def wpkggp_query(filter, blacklist):
    msg = b'Query'
    error_msg = None
    packages = []
    try:
        pipeHandle = CreateFile("\\\\.\\pipe\\WPKG", GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
    except pywintypes.error as e:
        # print "Error when generating pipe handle: %s" % e
        error_msg = u"Error: WPKG-GP Service not running"
        return error_msg

    SetNamedPipeHandleState(pipeHandle, PIPE_READMODE_MESSAGE, None, None)
    WriteFile(pipeHandle, msg)
    n = 0
    while 1:
        try:
            (hr, readmsg) = ReadFile(pipeHandle, 512)
            out = readmsg[4:].decode('utf-8')  # Strip 3 digit status code and decode
            status_code = int(readmsg[:3])
            if status_code == 103:
                # query output
                for x in ['TASK: ', 'NAME: ', 'REVISION: ']:
                    out = out.replace(x, '')
                    package = out.split('\t')
                # Filter Packages by task
                if package[0] in filter:
                    # Filter Packages by name
                    if not package[1].lower().startswith(blacklist):
                        packages.append(package)
            elif status_code == 104:
                # No pending updates
                continue
            elif status_code > 200:
                # errors
                if status_code == 203:
                    error_msg = 'Error: Query function not supported in the installed wpkg-gp version.'
                else:
                    error_msg = out

        except win32api.error as exc:
            if exc.winerror == winerror.ERROR_PIPE_BUSY:
                win32api.Sleep(5000)
                print('Pipe Busy Error')
                continue
            break

    if error_msg:
        return error_msg
    else:
        # Sort list by installs, updates, downgrades and removes
        sort_order = {"install": 0, "update": 1, "downgrade": 2, "remove": 3}
        packages.sort(key=lambda val: sort_order[val[0]])
        return packages

def get_local_packages(xml_path):
    def resolve_variable(child, pkg_version):
        variable = re.compile('(%.+?%)').findall(pkg_version)
        variable = ''.join(variable)
        variable_name = re.sub('%', '', variable)
        value = 'None'
        try:
            for entry in child.iterfind(u'variable[@name="{}"]'.format(variable_name)):
                value = entry.attrib['value']
            return (variable, value)
        except TypeError:
            return (variable, value)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    local_packages = {}
    for child in root.iter('package'):
        pkg_id = child.attrib['id']
        pkg_name = child.attrib['name']
        pkg_version = child.attrib['revision']
        if '%' in pkg_version:
                variable, value = resolve_variable(child, pkg_version)
                if '%' in value:
                    variable2, value2 = resolve_variable(child, value)
                    value = re.sub(variable2, value2, value)
                pkg_version = re.sub(variable, value, pkg_version)
        local_packages[pkg_id] = [pkg_name, pkg_version]
    return local_packages

def get_remote_packages(url):
    e = None
    try:
        xml = urllib.urlopen(url, timeout=5).read()
    except (IOError, urllib.URLError) as e:
        print(str(e))
        return {}, str(e)
    root = ET.fromstring(xml)
    remote_packages = {}
    for child in root.iter('package'):
        pkg_id = child.attrib['id']
        pkg_version = child.attrib['version']
        remote_packages[pkg_id] = pkg_version
    return remote_packages, e

def version_compare(local, remote, blacklist):
    # Comparing Version Numbers:
    # http://stackoverflow.com/questions/11887762/compare-version-strings
    update_list = []
    for package in local:
        try:
            if parse_version(local[package][1]) < parse_version(remote[package]):
                if not local[package][0].lower().startswith(blacklist):
                    update_list.append(('update',local[package][0], remote[package]))
        except KeyError:
            continue
    return update_list

def check_eventlog(start_time):
    # Parse Windows EVENT LOG Source
    # Source: http://docs.activestate.com/activepython/3.3/pywin32/Windows_NT_Eventlog.html

    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ

    # This dict converts the event type into a human readable form
    evt_dict = {win32con.EVENTLOG_AUDIT_FAILURE: 'AUDIT_FAILURE',
                win32con.EVENTLOG_AUDIT_SUCCESS: 'AUDIT_SUCCESS',
                win32con.EVENTLOG_INFORMATION_TYPE: 'INFORMATION',
                win32con.EVENTLOG_WARNING_TYPE: 'WARNING',
                win32con.EVENTLOG_ERROR_TYPE: 'ERROR',
                0: 'INFORMATION'}
    computer = 'localhost'
    logtype = 'Application'

    # open event log
    hand = win32evtlog.OpenEventLog(computer, logtype)

    log = []
    error_log = []
    try:
        events = 1
        while events:
            events = win32evtlog.ReadEventLog(hand, flags, 0)
            for ev_obj in events:
                the_time = ev_obj.TimeGenerated.Format()
                # '%c' is the locale date and time string format
                time_obj = parse(the_time)
                #time_obj = datetime.datetime.strptime(the_time, '%m/%d/%y %H:%M:%S')
                if time_obj < start_time:
                    #if time is old than the start time dont grab the data
                    break
                # data is recent enough
                computer = str(ev_obj.ComputerName)
                src = str(ev_obj.SourceName)
                evt_type = str(evt_dict[ev_obj.EventType])
                msg = UNICODE(win32evtlogutil.SafeFormatMessage(ev_obj, logtype))

                if (src == 'WSH'):  # Only Append WPKG Logs (WSH - Windows Scripting Host)
                    # Skip suppressed user notification info
                    if not msg.startswith('User notification suppressed.'):
                        log.append(string.join((the_time, computer, src, evt_type, '\n' + msg), ' : '))
                    # Create additional error log if there are warnings or errors
                    if (evt_type == "ERROR") or (evt_type == "WARNING"):
                        # Only Append Errors and Warnings
                        if "msiexec" in msg:
                            try:
                                exit_code = re.compile("\(([0-9]|[0-9]{2}|[0-9]{4})\)").search(msg).groups()[0]
                                msg = msg + "MSI error ({}): {}".format(exit_code, msi_exit_dic[exit_code])
                            except (AttributeError, KeyError):
                                print('Couldnt determine MSI Exit Code')
                        error_log.append(string.join((the_time, computer, src, evt_type, '\n' + msg), ' : '))

            if time_obj < start_time:
                break  # get out of while loop as well
        win32evtlog.CloseEventLog(hand)
    except:
        print(traceback.print_exc(sys.exc_info()))
    return log, error_log