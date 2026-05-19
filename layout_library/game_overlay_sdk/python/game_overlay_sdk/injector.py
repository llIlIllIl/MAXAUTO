import os
import ctypes
import numpy
from numpy.ctypeslib import ndpointer
import platform
import struct
import enum
import logging
from collections import deque
import sys
from pathlib import Path


class CustomExitCodes (enum.Enum):

    STATUS_OK = 0
    TARGET_PROCESS_IS_NOT_CREATED_ERROR = 1
    PROCESS_MONITOR_ALREADY_RUNNING_ERROR = 2
    PROCESS_MONITOR_IS_NOT_RUNNING_ERROR = 3
    GENERAL_ERROR = 4
    PATH_NOT_FOUND_ERROR = 5
    TARGET_PROCESS_WAS_TERMINATED_ERROR = 6


class InjectionError (Exception):
    def __init__ (self, message, exit_code):
        detailed_message = '%s:%d %s' % (CustomExitCodes (exit_code).name, exit_code, message)
        super (InjectionError, self).__init__ (detailed_message)
        self.exit_code = exit_code


def _package_dir ():
    package_dir = Path (__file__).resolve ().parent
    if package_dir.exists ():
        return package_dir
    if hasattr (sys, '_MEIPASS'):
        return Path (sys._MEIPASS) / 'game_overlay_sdk'
    return package_dir


def _lib_dir ():
    package_lib = _package_dir () / 'lib'
    if package_lib.exists ():
        return package_lib
    raise FileNotFoundError ('game_overlay_sdk/lib directory was not found')


def _lib_path (name):
    return str ((_lib_dir () / name).resolve ())


class InjectorDLL (object):

    __instance = None

    @classmethod
    def get_instance (cls):
        if cls.__instance is None:
            if platform.system () != 'Windows':
                raise Exception ("For now only Windows is supported, detected platform is %s" % platform.system ())
            cls.__instance = cls ()
        return cls.__instance

    def __init__ (self):
        if struct.calcsize ("P") * 8 == 64:
            self.lib = ctypes.cdll.LoadLibrary (_lib_path ('DLLInjection64.dll'))
        else:
            self.lib = ctypes.cdll.LoadLibrary (_lib_path ('DLLInjection32.dll'))

        # start monitoring
        self.StartMonitor = self.lib.StartMonitor
        self.StartMonitor.restype = ctypes.c_int
        self.StartMonitor.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p
        ]

        # stop monitorring
        self.ReleaseResources = self.lib.ReleaseResources
        self.ReleaseResources.restype = ctypes.c_int
        self.ReleaseResources.argtypes = []

        # set log level
        self.SetLogLevel = self.lib.SetLogLevel
        self.SetLogLevel.restype = ctypes.c_int
        self.SetLogLevel.argtypes = [
            ctypes.c_int
        ]

        # get pid
        self.GetPid = self.lib.GetPid
        self.GetPid.restype = ctypes.c_int
        self.GetPid.argtypes = [
            ndpointer (ctypes.c_int64)
        ]

        # send message
        self.SendMessageToOverlay = self.lib.SendMessageToOverlay
        self.SendMessageToOverlay.restype = ctypes.c_int
        self.SendMessageToOverlay.argtypes = [
            ctypes.c_char_p
        ]

        self.SendBitmapToOverlay = getattr (self.lib, 'SendBitmapToOverlay', None)
        if self.SendBitmapToOverlay is not None:
            self.SendBitmapToOverlay.restype = ctypes.c_int
            self.SendBitmapToOverlay.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int
            ]

        # run process
        self.RunProcess = self.lib.RunProcess
        self.RunProcess.restype = ctypes.c_int
        self.RunProcess.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p
        ]


def start_monitor (process_name):
    logging.warning ('For Steam Games ensure that there is steam_appid.txt file in %SteamFolder%\\steamapps\\common\\%GameName% with correct appid! You can get app_id here https://steamdb.info/search/')
    location = str (_lib_dir ().resolve ())
    res = InjectorDLL.get_instance ().StartMonitor (process_name.encode (), location.encode ())
    if res != CustomExitCodes.STATUS_OK.value:
        raise InjectionError ('start process creation monitoring error please check logs', res)

def release_resources ():
    res = InjectorDLL.get_instance ().ReleaseResources ()
    if res != CustomExitCodes.STATUS_OK.value:
        raise InjectionError ('stop monitoring error', res)

def set_log_level (level):
    res = InjectorDLL.get_instance ().SetLogLevel (level)
    if res != CustomExitCodes.STATUS_OK.value:
        raise InjectionError ('failed to set log level', res)

# log level for core module of this library, not related to python logging
def enable_monitor_logger ():
    set_log_level (2)

def disble_monitor_logger ():
    set_log_level (6)

def enable_dev_logger ():
    set_log_level (0)

def get_pid ():
    pid = numpy.zeros (1).astype (numpy.int64)
    res = InjectorDLL.get_instance ().GetPid (pid)
    if res != CustomExitCodes.STATUS_OK.value:
        raise InjectionError ('Callback has not been called yet', res)
    return pid[0]

def send_message (message):
    if not hasattr (send_message, 'message_queue'):
        send_message.message_queue = deque (maxlen = 5)
    send_message.message_queue.append (message)
    acum_message = ''
    for msg in send_message.message_queue:
        acum_message = acum_message + msg + '\n'
    res = InjectorDLL.get_instance ().SendMessageToOverlay (acum_message.encode ())
    if res != CustomExitCodes.STATUS_OK.value:
        raise InjectionError ('failed to send message', res)

def send_bitmap_frame (frame=None, visible=True, width=None, height=None, stride=None, seq=0, rgba=None, pixels=None):
    if isinstance (frame, dict):
        visible = frame.get ('visible', visible)
        width = frame.get ('width', width)
        height = frame.get ('height', height)
        stride = frame.get ('stride', stride)
        seq = frame.get ('seq', seq)
        rgba = frame.get ('rgba', frame.get ('pixels', rgba))
    elif frame is not None:
        rgba = frame

    if rgba is None:
        rgba = pixels
    if rgba is None:
        raise ValueError ('rgba bytes are required')
    if width is None or height is None:
        raise ValueError ('width and height are required')
    if stride is None:
        stride = int (width) * 4

    data = bytes (rgba)
    expected = int (stride) * int (height)
    if len (data) < expected:
        raise ValueError ('rgba bytes are shorter than stride * height')

    sender = InjectorDLL.get_instance ().SendBitmapToOverlay
    if sender is None:
        raise InjectionError ('bitmap API is not available in DLLInjection', CustomExitCodes.GENERAL_ERROR.value)
    buffer = ctypes.create_string_buffer (data)
    res = sender (int (bool (visible)), int (width), int (height), int (stride), int (seq), buffer, len (data))
    if res != CustomExitCodes.STATUS_OK.value:
        raise InjectionError ('failed to send bitmap frame', res)

def send_overlay_frame (*args, **kwargs):
    return send_bitmap_frame (*args, **kwargs)

def send_bitmap (*args, **kwargs):
    return send_bitmap_frame (*args, **kwargs)

def clear_bitmap_frame ():
    return send_bitmap_frame (
        visible=False,
        width=1,
        height=1,
        stride=4,
        seq=0,
        rgba=b'\x00\x00\x00\x00'
    )

def clear_overlay_frame ():
    return clear_bitmap_frame ()

def clear_bitmap ():
    return clear_bitmap_frame ()

def write_app_id (file_path, app_id):
    logging.info ('writing %s to %s' % (str (app_id), file_path))
    with open (file_path, 'w') as f:
        f.write (str(app_id))

def run_process (exe_path, exe_args = "", steam_app_id = None):
    if steam_app_id is None:
        logging.warning ('For Steam Games please provide app id or ensure that there is steam_appid.txt file in game folder! You can get app_id here https://steamdb.info/search/')
    elif not os.path.isabs (exe_path):
        logging.warning ('to create steam_appid.txt file please provide full path to executable')
        raise Exception ('please provide full path')

    game_dir = os.path.abspath (os.path.dirname (exe_path))
    steam_app_id_file = os.path.join (game_dir, 'steam_appid.txt')
    write_app_id (steam_app_id_file, steam_app_id)

    location = str (_lib_dir ().resolve ())
    res = InjectorDLL.get_instance ().RunProcess (exe_path.encode (), exe_args.encode(), location.encode ())
    if res != CustomExitCodes.STATUS_OK.value:
        raise InjectionError ('failed to run process please check logs', res)


class OvelrayLogHandler (logging.Handler):

    def __init__ (self):
        logging.Handler.__init__(self)

    def emit (self, record):
        try:
            send_message (self.format (record))
        except InjectionError as inj_err:
            # no need to notify about excpetion here cause it is implemented in cpp code
            pass
        except BaseException as e:
            self.handleError (record)
