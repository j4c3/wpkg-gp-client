# -*- encoding: utf-8 -*-
import wx, wx.adv
from sys import exit
from wx.lib.delayedresult import startWorker
from pubsub import pub
from threading import Thread
from utilities import *
from help import HelpDialog
from img import AppImages
import load_config

# set translation function
_ = wx.GetTranslation
#if you are getting unicode errors, try something like:
#_ = lambda s: wx.GetTranslation(s).encode('utf-8')

# get program path
path = get_client_path()

# load Image class
img = AppImages(path)

# set path to wpkg.xml and get system architecture
xml_file, arch = arch_check()

req_wpkggp_ver = '0.17.17'
app_name = 'WPKG-GP Client'

#Change working directory to get relative paths working for the images in the help files:
os.chdir(path)

# Loading and setting INI settings:
# ---------------------------------
try:
    ini = load_config.ConfigIni(os.path.join(path, 'wpkg-gp_client.ini'))
except load_config.NoConfigFile as error_msg:
    # Config file could not be opened!
    print(error_msg)
    no_config = True
else:
    no_config = False
    # General
    allow_quit = ini.loadsetting('General', 'allow quit')
    check_last_upgrade = ini.loadsetting('General', 'check last update')
    last_upgrade_interval = ini.loadsetting('General', 'last update interval')
    if not isinstance(last_upgrade_interval, (int)):
        last_upgrade_interval = 14
    check_vpn = ini.loadsetting('General', 'check vpn')
    disable_shutdown_checkbox = ini.loadsetting('General', 'disable shutdown checkbox')
    shutdown_timeout = ini.loadsetting('General', 'shutdown timeout')
    if not isinstance(shutdown_timeout, (int)):
        shutdown_timeout = 30
    help_file = ini.loadsetting('General', 'help file')
    # Update Check method
    update_method = ini.loadsetting('Update Check', 'method')
    if update_method not in ['wpkg-gp', 'updatefile'] and update_method != False:
        update_method = 'wpkg-gp'
    # Update Check filter
    try:
        raw_update_filter = ini.loadsetting('Update Check', 'filter').strip().split(';')
    except AttributeError:
        raw_update_filter = ''
    available_filter = ('update', 'install', 'downgrade', 'remove')
    if raw_update_filter == 'all' or raw_update_filter == '':
        update_filter = available_filter
    else:
        update_filter = tuple([entry for entry in raw_update_filter if entry in available_filter])
    # Update Check blacklist
    try:
        raw_update_blacklist = ini.loadsetting('Update Check', 'blacklist').lower().strip().split(';')
    except AttributeError:
        raw_update_blacklist = ''
    update_blacklist = tuple(raw_update_blacklist)
    update_startup = ini.loadsetting('Update Check', 'startup')
    update_interval = ini.loadsetting('Update Check', 'interval')
    if isinstance(update_interval, (int)):
        # Transform Minutes to Milliseconds for wx.python timer
        update_interval = update_interval * 60 * 1000
    else:
        update_interval = False
    update_url = ini.loadsetting('Update Check', 'update url')
    check_bootup_log = ini.loadsetting('General', 'check boot log')

def create_menu_item(menu, label, image, func):
    item = wx.MenuItem(menu, -1, label)
    item.SetBitmap(img.get(image))
    menu.Bind(wx.EVT_MENU, func, id=item.GetId())
    menu.Append(item)
    return item

class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, trayicon, tooltip):
        super(TaskBarIcon, self).__init__()
        self.show_no_updates = False

        # Set trayicon and tooltip
        icon = wx.Icon(wx.Bitmap(trayicon))
        self.SetIcon(icon, tooltip)

        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_upgrade)
        self.Bind(wx.adv.EVT_TASKBAR_BALLOON_CLICK, self.on_bubble)
        self.upd_error_count = 0
        self.checking_updates = False
        self.updates_available = False
        self.shutdown_scheduled = False
        self.reboot_scheduled = False
        self.bootup_time = getBootUp()
        if update_interval and update_method:
            self.timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
            self.timer.Start(update_interval)
            if update_startup:
                self.on_timer(None)
        if check_bootup_log:
            last_check = ReadLastSyncTime()
            now = datetime.datetime.now()
            if (self.bootup_time + datetime.timedelta(hours=1) > now) and \
               (self.bootup_time + datetime.timedelta(minutes=30) > last_check):
                log, errorlog, reboot = check_eventlog(self.bootup_time)
                if errorlog:
                    error_str = _(u"Update error detected\n"
                                  u"during system start up.")
                    self.ShowBalloon(title=_(u'WPKG Error'), text=error_str, msec=20*1000, flags=wx.ICON_ERROR)
                    title = _(u"System start error")
                    dlg = ViewLogDialog(title=title,log=errorlog)
                    dlg.ShowModal()
        if check_last_upgrade:
            # Check when WPKG-GP sucessfully synced the last time
            # Inform USER that he should upgrade the System
            last_sync = ReadLastSyncTime()
            if last_sync:
                if last_sync < (datetime.datetime.now() - datetime.timedelta(days=last_upgrade_interval)):
                    dlg_str = _(u"System should be updated!\n\n"
                                u"System wasn't updated in over {} days.").format(str(last_upgrade_interval))
                    dlg = wx.MessageDialog(None, dlg_str, _(u"Attention!"), wx.OK | wx.ICON_EXCLAMATION)
                    dlg.ShowModal()
                    self.on_upgrade(None)
        EVT_RESULT(self, self.PipeEventResult)
        PipeServerThread(self, sessionID=session_ID)

    def PipeEventResult(self, msg):
        if msg.data:
            self.on_upgrade(None)

    def CreatePopupMenu(self):
        menu = wx.Menu()
        if update_method:
            create_menu_item(menu, _(u"Check for updates"), "update", self.manual_timer)
        create_menu_item(menu, _(u"System update"), "upgrade", self.on_upgrade)
        menu.AppendSeparator()
        create_menu_item(menu, _(u"Help"), "help", self.on_about)
        if self.shutdown_scheduled:
            menu.AppendSeparator()
            create_menu_item(menu, _(u"Cancel shutdown"), "cancel", self.on_cancleshutdown)
        if allow_quit:
            menu.AppendSeparator()
            create_menu_item(menu, _(u"Close"), "quit", self.on_exit)
        return menu

    def manual_timer(self, evt):
        self.show_no_updates = True
        self.on_timer(evt)

    def on_timer(self, evt):
        if update_method == 'wpkg-gp':
            if wpkg_running():
                return
        startWorker(self.update_check_done, self.update_check)

    def update_check(self):
        # Update Check function
        if update_method == 'wpkg-gp':
            updates = wpkggp_query(update_filter, update_blacklist)
        else:
            local_packages = get_local_packages(xml_file)
            remote_packages, e = get_remote_packages(update_url)
            if e:
                return str(e)
            updates = version_compare(local_packages, remote_packages, update_blacklist)
        return updates

    def update_check_done(self, result):
        # Update check function ended
        r = result.get()
        self.checking_updates = False
        if isinstance(r, str):
            # Error returned
            self.updates_available = False
            if self.upd_error_count < 2 and not self.show_no_updates:
                # only display update errors on automatic check after the third error in a row
                self.upd_error_count += 1
            else:
                error_str = _(u"Could not load updates:") + "\n" + r
                self.ShowBalloon(title=_(u'Update Error'), text=error_str, msec=20*1000, flags=wx.ICON_ERROR)
                # reset update error counter
                self.upd_error_count = 0
        elif r:
            self.upd_error_count = 0
            action_dict = {'update': _(u'UPD:') + '\t',
                           'install': _(u'NEW:') + '\t',
                           'remove': _(u'REM:') + '\t',
                           'downgrade': _(u'DOW:') + '\t'}
            # Updates Found
            self.updates_available = True
            text = ''
            for action, name, version in r:
                text += action_dict[action] + name + ', v. ' + version + '\n'
            self.ShowBalloon(title=_(u"Update(s) available:"), text=text, msec=20*1000, flags=wx.ICON_INFORMATION)
        else:
            # No Updates Found
            self.upd_error_count = 0
            self.updates_available = False
            if self.show_no_updates:
                self.ShowBalloon(title=_(u"No Updates"), text=" ", msec=5 * 1000, flags=wx.ICON_INFORMATION)
                self.show_no_updates = False

    def on_bubble(self, event):
        if self.updates_available:
            self.on_upgrade(None)

    def on_upgrade(self, event):
        try:
            if self.wpkg_dialog.IsShown():
                # If dialog is opened already, raise window to top
                self.wpkg_dialog.Raise()
                return
        except AttributeError:
            # Dialog is not opened yet
            # Check if Reboot is Pending
            try:
                reboot_pending = ReadRebootPendingTime()
            except WindowsError:
                dlg_msg = _(u'Registry Error\n\nNo access to necessary registry key.')
                dlg = wx.MessageDialog(None, dlg_msg, app_name, wx.OK | wx.ICON_ERROR)
                dlg.ShowModal()
                dlg.Destroy()
                return
            if reboot_pending and reboot_pending > self.bootup_time:
                dlg_msg = _(u"Reboot required!\n\n"
                           u"A reboot is required before the system\n"
                           u"can be updated again.\n"
                           u"Reboot now?")
                dlg = wx.MessageDialog(None, dlg_msg, app_name, wx.YES_NO | wx.YES_DEFAULT | wx.ICON_EXCLAMATION)
                if dlg.ShowModal() == wx.ID_YES:
                    # Initiate Reboot
                    shutdown(1, time=5, msg=_(u"System will reboot now!"))
                    return
                else:
                    return
            elif reboot_pending:
                SetRebootPendingTime(reset=True)
            if update_method and update_interval:
                self.timer.Stop()
            self.wpkg_dialog = RunWPKGDialog(parent=self, title=_(u'System Update'))
            self.wpkg_dialog.ShowModal()
            if self.wpkg_dialog.shutdown_scheduled == True:
                # Shutdown Scheduled add Cancel Option to Popup Menu
                self.shutdown_scheduled = True
            if self.wpkg_dialog.reboot_scheduled == True:
                # Reboot Scheduled add Cancel Option to Popup Menu
                self.shutdown_scheduled = True
                self.reboot_scheduled = True
            self.wpkg_dialog.Destroy()
            # Not deleting this threw an error opening the dialog a second time after closing.
            del(self.wpkg_dialog)
            if update_method and update_interval:
                self.timer.Start()

    def on_about(self, evt):
        helpfile = os.path.join(path + help_file)
        helpdlg = HelpDialog(helpfile, title=_(u'WPKG-GP Client - Help'))
        helpdlg.Center()
        helpdlg.ShowModal()

    def on_cancleshutdown(self, event):
        if self.reboot_scheduled:
            # If reboot is canceled, set reboot pending time to registry
            SetRebootPendingTime()
        shutdown(3)  # Cancel Shutdown
        self.reboot_scheduled = False
        self.shutdown_scheduled = False

    def on_exit(self, event):
        try:
            if self.wpkg_dialog.IsShown():
                # Raise window to top
                self.wpkg_dialog.Raise()
                return
        except:
            self.Destroy()

class RunWPKGDialog(wx.Dialog):
    def __init__(self, parent=None, title='Temp'):
        """Constructor"""
        wx.Dialog.__init__(self, None, title=title)
        self.parent = parent
        self.shouldAbort = False
        self.running = False
        self.wpkg_start_time = None
        self.shutdown_scheduled = False
        self.reboot_scheduled = False
        self.log = ""
        self.InitUI()
        size_y = self.GetEffectiveMinSize()[1]
        self.SetSize((410, size_y))

    def InitUI(self):
        self.panel = wx.Panel(self, wx.ID_ANY)
        # Info Text
        infotext = _(u'Please save your work and close all open aplications before updating.  Applications left running may be terminated '
                     u'and/or the system could reboot without further confirmation.')

        infobox = wx.StaticBox(self.panel, -1, _(u'Attention'))
        infoboxbsizer = wx.StaticBoxSizer(infobox, wx.VERTICAL)
        info = wx.StaticText(self.panel, label=infotext)
        info.Wrap(380)
        infoboxbsizer.Add(info, 0)

        self.gauge = wx.Gauge(self.panel, size=(24, 26))
        self.update_label = wx.StaticText(self.panel, label=_(u'Current Progress:'))
        self.update_box = wx.TextCtrl(self.panel, style=wx.TE_READONLY)
        self.update_box.SetBackgroundColour(wx.WHITE)
        self.chk_shutdown = wx.CheckBox(self.panel, size=(160,20), label=_(u"Shutdown after update"))
        self.logButton = wx.Button(self.panel, size=(54,26), label="LOG")
        self.logButton.SetToolTip(wx.ToolTip(_(u'Open WPKG Log')))
        self.logButton.SetBitmap(img.get('log'))
        self.startButton = wx.Button(self.panel, label=_(u"Update"))
        self.abortButton = wx.Button(self.panel, label=_(u"Cancel"))
        if disable_shutdown_checkbox:
            self.chk_shutdown.Disable()
        self.logButton.Disable()
        self.abortButton.Disable()

        self.line = wx.StaticLine(self.panel, -1, size=(2,2), style=wx.LI_HORIZONTAL)
        self.startButton.Bind(wx.EVT_BUTTON, self.OnStartButton)
        self.abortButton.Bind(wx.EVT_BUTTON, self.OnAbortButton)
        self.logButton.Bind(wx.EVT_BUTTON, self.OnLogButton)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer.Add(infoboxbsizer, 0, wx.ALL | wx.EXPAND, 5)
        self.sizer.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 5)
        self.sizer.Add(self.update_label, 0, wx.ALL | wx.EXPAND, 5)
        self.sizer.Add(self.update_box, 0, wx.ALL | wx.EXPAND, 5)
        self.sizer.Add(self.line, 0, wx.ALL | wx.EXPAND, 5)
        self.sizer.Add(self.chk_shutdown, 0, wx.LEFT | wx.EXPAND, 7)
        self.sizer2.Add(self.logButton, 0)
        self.sizer2.AddStretchSpacer()
        self.sizer2.Add(self.startButton, 0)#, wx.RIGHT, 2)
        self.sizer2.Add(self.abortButton, 0)
        self.sizer.Add(self.sizer2, 0, wx.ALL | wx.EXPAND, 5)
        self.panel.SetSizerAndFit(self.sizer)
        self.Center()

    def OnStartButton(self, e):
        if wpkg_running():
            dlg_msg = _(u"WPKG is currently running,\n"
                        u"please wait a few seconds and try again.")
            dlg = wx.MessageDialog(self, dlg_msg, app_name, wx.OK | wx.ICON_EXCLAMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return
        dlg_title = _(u"Warning")
        dlg_msg = _(u"Close all open applications!\n\nThe system could restart without further confirmation!\n\n" \
                    u"Continue?")
        dlg = wx.MessageDialog(self, dlg_msg, dlg_title, wx.YES_NO|wx.YES_DEFAULT|wx.ICON_EXCLAMATION)
        if dlg.ShowModal() == wx.ID_YES:
            dlg.Destroy()
            # Disable/enable buttons and disable Close Window option!
            self.startButton.Disable()
            self.abortButton.Enable()
            self.EnableCloseButton(enable=False)
            # Set Start Time
            self.wpkg_start_time = datetime.datetime.now()
            # Reset Log
            self.log = None
            startWorker(self.LongTaskDone, self.LongTask)

    def OnAbortButton(self, e):
        if not self.running:
            self.Close()
            return
        dlg_title = _(u"Cancel")
        dlg_msg = _(u"System update in progress!\n\n Canceling this process could result in installation issues.\n"
                    u"Cancel?")
        dlg = wx.MessageDialog(self, dlg_msg, dlg_title, wx.YES_NO|wx.YES_DEFAULT|wx.ICON_EXCLAMATION)
        if dlg.ShowModal() == wx.ID_YES:
            dlg.Destroy()
            if not self.running:
                # WPKG Process by this client has finished, no cancel possible
                return
            print('Aborting WPKG Process') #TODO: MOVE TO DEBUG LOGGER
            self.shouldAbort = True
            msg = 'Cancel'
            try:
                pipeHandle = CreateFile("\\\\.\\pipe\\WPKG", GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
            except pywintypes.error as e:
                print("Error when generating pipe handle: %s") % e #TODO: MOVE TO DEBUG LOGGER
                return 1

            SetNamedPipeHandleState(pipeHandle, PIPE_READMODE_MESSAGE, None, None)
            WriteFile(pipeHandle, msg)

    def LongTask(self):
        return_msg = None
        return_code = None
        reboot = False
        # Checking if System is connected through VPN
        if check_vpn and vpn_connected(arch=arch):
            dlg_msg = _(u"WPKG-GP Client detected a active VPN Connection using Cisco Anyconnect.\n"
                        u"This could result in slow upgrade progress and updates for the AnyConnect\n"
                        u"Software will be blocked.\n"
                        u"Continue?")
            dlg = wx.MessageDialog(self, dlg_msg, app_name, wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION)
            if dlg.ShowModal() == wx.ID_NO:
                # Canceled by user because of active VPN Connection
                return_msg = 'WPKG process start canceled by user.' # Make translate able?
                return 400, return_msg, None
        # LONG TASK is the PipeConnection to the WPKG-GP Windows Service
        self.running = True
        msg = b'ExecuteNoReboot'
        try:
            pipeHandle = CreateFile("\\\\.\\pipe\\WPKG", GENERIC_READ|GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
        except pywintypes.error as e:
            # print "Error when generating pipe handle: %s" % e
            # Can't connect to pipe error, probably service not running
            return_msg = u"Error: WPKG-GP Service not running"
            return 208, return_msg, None

        SetNamedPipeHandleState(pipeHandle, PIPE_READMODE_MESSAGE, None, None)
        WriteFile(pipeHandle, msg)
        while 1:
            try:
                (hr, readmsg) = ReadFile(pipeHandle, 512)
                out = readmsg[4:].decode('utf-8')  #Strip 3 digit status code, decode characters
                status_code = int(readmsg[:3])
                if status_code < 102:
                    # default status code for pipe updates
                    percentage = getPercentage(out)
                    wx.CallAfter(self.update_box.SetValue, out)
                    wx.CallAfter(self.gauge.SetValue, percentage)
                elif status_code > 300:
                    # reboot necessary
                    reboot = True
                elif status_code > 200:
                    # possible error
                    return_code = status_code
                    return_msg = out
            except win32api.error as exc:
                if exc.winerror == winerror.ERROR_PIPE_BUSY:
                    win32api.Sleep(5000)
                    print('Pipe Busy Error')
                    continue
                break

        return return_code, return_msg, reboot

    def LongTaskDone(self, result):
        self.running = False
        self.chk_shutdown.Disable()
        if disable_shutdown_checkbox:
            chk_shutdown = False
        else:
            chk_shutdown = self.chk_shutdown.IsChecked()
        self.gauge.SetValue(100)
        return_code, return_msg, reboot = result.get()
        # Get WPKG Log
        self.log, error_log = check_eventlog(self.wpkg_start_time)
        if self.shouldAbort:
            self.update_box.SetValue(_(u'WPKG-GP process aborted.'))
            if return_code == 200:
                # display the error msg ?
                print(return_msg)
        elif return_code == 400 or return_code == 105:
            self.update_box.SetValue(return_msg)
        elif return_code and return_code != 200:
            self.update_box.SetValue(return_msg)
            dlg_title = _(u"WPKG-GP Notification")
            dlg_icon = wx.ICON_INFORMATION
            if return_code == 201:
                dlg_msg = _(u"WPKG-GP is currently running a task.\n"
                            u"Retry later.")
            elif return_code == 204:
                dlg_msg = _(u"The update server could not be reached.")
                dlg_icon = wx.ICON_ERROR
            elif return_code == 205:
                dlg_msg = _(u"The system was rejected from the server to execute an update!\n"
                            u"Contact your IT department for further information.")
            elif return_code == 207:
                dlg_msg = _(u"You are not authorized to execute a wpkg update!\n"
                            u"Contact your IT department for further information.")
            elif return_code == 208:
                dlg_msg = _(u"Can't connect to the wpkg-gp service.")
                dlg_icon = wx.ICON_ERROR
            else:
                dlg_msg = _(u'Unknown problem occured.') + '\n Status code: ' + str(return_code) + '\n' + return_msg
            dlg = wx.MessageDialog(self, dlg_msg, dlg_title, wx.OK | dlg_icon)
            dlg.ShowModal()
        else:
            if reboot:
                self.update_box.SetValue(_(u'WPKG-GP process finished, restart necessary!'))
            else:
                self.update_box.SetValue(_(u'WPKG-GP process finished.'))
        if error_log:
            log_dlg = ViewLogDialog(title=_(u"Error detected during update"), log=error_log)
            log_dlg.ShowModal()
            log_dlg.Destroy()
        if reboot and not chk_shutdown and not self.shouldAbort:
            # reboot pending, no abort and no shutdown configured
            dlg_msg = _(u"Reboot required!\n\n"
                        u"For the completion of the installation(s), a reboot is required.\n"
                        u"Reboot now?")
            dlg = wx.MessageDialog(self, dlg_msg, app_name, wx.YES_NO | wx.YES_DEFAULT | wx.ICON_EXCLAMATION)
            if dlg.ShowModal() == wx.ID_YES:
                # Initiate reboot
                shutdown(1, time=shutdown_timeout, msg=_(u'System will reboot in %TIME% seconds.'))
                self.reboot_scheduled = True
                self.Close()
            else:
                # Reboot is pending
                SetRebootPendingTime()
        elif chk_shutdown and not self.shouldAbort and not return_code:
            # shutdown configured, wpkg process not canceled and no error occurred
            shutdown(2, time=shutdown_timeout, msg=_(u'System will shutdown in %TIME% seconds.'))
            if reboot:
                self.reboot_scheduled = True
            else:
                self.shutdown_scheduled = True
            self.Close()
        if not self.log:
            self.log.append(_(u"No System changes."))
        self.logButton.Enable()
        self.abortButton.SetLabel(_(u'Close'))
        self.shouldAbort = False
        self.EnableCloseButton(enable=True)

    def OnLogButton(self, evt):
        logdlg = ViewLogDialog(title='WPKG Log - {}'.format(self.wpkg_start_time.strftime("%Y/%m/%d %H:%M:%S")),
                               log=self.log)
        logdlg.ShowModal()

class ViewLogDialog(wx.Dialog):
    def __init__(self, title='Temp', log="Temp"):
        """Constructor"""
        wx.Dialog.__init__(self, None, title=title, style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.log = "\n".join(log)
        self.InitUI()
        self.SetSize((640, 480))

    def InitUI(self):
        self.panel = wx.Panel(self, wx.ID_ANY)
        self.textbox = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.textbox.SetValue(self.log)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.textbox, 1, wx.ALL | wx.EXPAND, 5)
        self.panel.SetSizerAndFit(self.sizer)
        self.Center()
        self.Bind(wx.EVT_CLOSE, self.OnClose)

    def OnClose(self, evt):
        self.Destroy()

EVT_RESULT_ID = wx.ID_ANY

def EVT_RESULT(win, func):
    win.Connect(-1, -1, EVT_RESULT_ID, func)

class PipeEvent(wx.PyEvent):
    def __init__(self, data):
        wx.PyEvent.__init__(self)
        self.SetEventType(EVT_RESULT_ID)
        self.data = data

class PipeServerThread(Thread):
    def __init__(self, wxObject, sessionID):
        Thread.__init__(self)
        self._wxObject = wxObject
        self.sessionID = sessionID
        self.start()

    def run(self):
        while True:
            pipeMsg = pipe_server(self.sessionID)
            wx.PostEvent(self._wxObject, PipeEvent(pipeMsg))

if __name__ == '__main__':
    app = wx.App(False)

    # Translation configuration
    mylocale = wx.Locale(wx.LANGUAGE_DEFAULT)
    # TODO: Add config option or settings to force language? e.g.: wx.Locale(language=wx.LANGUAGE_FRENCH)
    localedir = os.path.join(path, "locale")
    mylocale.AddCatalogLookupPathPrefix(localedir)
    mylocale.AddCatalog('wpkg-gp-client')

    # If config file could not be opened
    if no_config:
        dlgmsg = _(u'Can\'t open config file "{}"!').format("wpkg-gp_client.ini")
        dlg = wx.MessageDialog(None, dlgmsg, app_name, wx.OK | wx.ICON_ERROR)
        dlg.ShowModal()
        exit(1)

    # If an instance of WPKG-GP Client is running already in the users session
    (client_running_value, sessionID) = client_running()
    if client_running_value:
        # Notify existing instance
        pipe_client(sessionID)
        app.Destroy()
        exit(1)
    else:
        session_ID = sessionID

    if not wpkggp_version(req_wpkggp_ver):
        dlgmsg = _(u"WPKG-GP Client requires at least version"
                   u" {} of the WPKG-GP Service.").format(req_wpkggp_ver)
        dlg = wx.MessageDialog(None, dlgmsg, app_name, wx.OK | wx.ICON_ERROR)
        dlg.ShowModal()
        exit(1)

    # Set help file
    lang_int = mylocale.GetLanguage()
    lang = wx.Locale.GetLanguageCanonicalName(lang_int)
    if not help_file or help_file.lower() == "default":
        help_file = get_help_translation(path, lang)

    TRAY_ICON = os.path.join(path, 'img', 'apacheconf-16.png')
    taskbarIcon = TaskBarIcon(trayicon=TRAY_ICON, tooltip=app_name)

    app.MainLoop()