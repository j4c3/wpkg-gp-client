##Overview
- [Introduction](#introduction)
- [Update Notifications](#updates)
- [Update System](#upgrade)
- [Errors during update](#error)
- [Credits](#credits)

<a name="introduction">
##Introduction
WPKG-GP Client is a graphical user interface which allows users without elevated rights to manually process [WPKG](https://wpkg.org/) packages. 
The application loads at login and notifies of pending updates.

The Application is coded in Python/wxPython and relies on a [modified version of WPKG-GP](https://github.com/sonicnkt/wpkg-gp/).

<a name="updates">
##Update Notifications
The application informs the user of pending updates at an administratively configurable interval.

![Update Benachrichtigung](help\help_en_01.jpg)

|Indicator|Description|
|---------|:---------|
|NEW      |New software package will be installed|
|UPD      |Installed package will be updated|
|DOW      |Installed package will be downgraded|
|REM      |Installed package will be removed|

Notifications may be configured to only display some types of pending tasks.

Addiitonally, the update database for WPKG-GP Client is independent of the actual WPKG package database on the update server, so
it is possible for pending updates to exist that have not triggered a notification. 

You can manually check for pending updates by choosing __Check for updates__ from the context menu of the taskbar notification area icon.

<a name="upgrade">
##Update System
Double-clicking the tray icon, selecting the option __System update__ or clicking on an update notification bubble opens
up the _System Update_ dialog from which you can start a manual update of the installed software packages.

__Attention:__
You should close all applications and save any open documents prior to initiating the update process.  Applications can close without warning and the system may restart without further conformation.

![System Update](help\help_en_02.jpg)

Current progress of the update process is displayed using a progress bar and a text field indicating the current task.
Keep in mind that the progress bar only displays progress in the number of packages processed, and is not an indicator of the remaining. 

When the update process finishes it will be shown by a full progress bar and the information "WPKG Process Finished" in 
the current progress text field. You can display the details of tasks performed by selecting the "__Log__"  option.

Some applications may require a system restart after installation. In most cases this wont be forced and 
the current user will be prompted to restart the system. Additional system updates will be blocked until the system has been
restarted.

![Restart necessary](help\help_en_03.jpg)

You can select the option __Shutdown after update__ before or during the update process. 

If a reboot or shutdown has been initiated, this can be canceled by selecting the option __Cancel shutdown__ from the 
tray icons context menu. 

<a name="error">
##Errors during update
If an error occurs during the update process an error log will be opened automatically upon completion.  Configured shutdown won't be executed.

<a name="credits">
##Credits
__WPKG-GP Client__ was developed by _Nils Thiele_.

Project: wpkg-gp-client <https://github.com/sonicnkt/wpkg-gp-client/><br/>
Copyright (c) 2016 _Nils Thiele_.

Project: wpkg-gp modification <https://github.com/sonicnkt/wpkg-gp/><br/>
Copyright (c) 2016 _Nils Thiele_.

__WPKG-GP Client__ uses code from other opensource projects:

- Project: wxPython <https://www.wxpython.org/>
- Project: pyWin32 <https://github.com/mhammond/pywin32>
- Project: python-markdown2 <https://github.com/trentm/python-markdown2/>
    - Copyright (c) 2012 _Trent Mick_.
    - License ([MIT License](https://github.com/trentm/python-markdown2/blob/master/LICENSE.txt))
- Project: wpkg-gp <https://github.com/cleitet/wpkg-gp>
    - Copyright 2010, 2011 _The WPKG-GP team_
- Project: WindowsNT Eventlog Code from [ActiveStates.com](http://docs.activestate.com/activepython/3.3/pywin32/Windows_NT_Eventlog.html)
    - Code Author: _John Nielsen_

__Translations:__

- spanish by _Julio San José Antolín_
- brazilian portuguese by [_jader31_](https://github.com/jader31)
