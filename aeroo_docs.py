#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
################################################################################
#
# Copyright (c) 2009-2014 Alistek ( http://www.alistek.com ) 
#               All Rights Reserved.
#               General contacts <info@alistek.com>
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsability of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# garantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
################################################################################

import sys, os

from signal import SIGQUIT
from time import time, sleep
from threading import Thread, Event
from wsgiref.simple_server import make_server

from argparse import ArgumentParser
from configparser import ConfigParser
from collections import OrderedDict

from daemonize import Daemonize
from jsonrpc2 import JsonRpcApplication

#from aeroo_docs_fncs import OfficeService
import aeroo_docs_fncs as adf # For monkey patch.

import logging


#### Prepare spool directory
SPOOL_PATH = ''
PRESERVE_FH = []


##### Starts timer for cleaning up spool directory        
class CleanerThread(Thread):
    
    def __init__(self, delay=60, expire=1800):
        super(CleanerThread, self).__init__()
        self.name = 'Cleaner thread'
        self.delay = delay
        self.expire = expire

    def run(self):
        while True:
            files = os.listdir(args.spool_directory)
            for fname in files:
                testfile = SPOOL_PATH % fname
                atribs = os.stat(testfile)
                if int(time()) - atribs.st_mtime > self.expire:
                    os.unlink(testfile)
            sleep(self.delay)


def main():
    """
    Main worker thread.
    """
    logger = logging.getLogger('main')
    if not args.no_cleanup:
        new_cleaner = CleanerThread(expire=args.spool_expire)
        new_cleaner.setDaemon(True)
        new_cleaner.start()
    if args.simple_auth:
        auth_type =  lambda u, p: args.username == u and args.password == p
    else:
        auth_type =  lambda *a: True
    try:
        #oser = OfficeService(args.oo_server, args.oo_port, args.spool_directory, auth_type)
        oser = adf.OfficeService(args.oo_server, args.oo_port, args.spool_directory, auth_type)
        def _readFile(ident):
            with open(oser.spool_path % oser._md5(str(ident)), "r") as tmpfile:
                data = tmpfile.read()
            return adf.base64.b64decode(data.encode())
        # Monkey patch to fix bugs.
        adf._readFile = oser._readFile = _readFile
    except Exception as e:
        logger.info('...failed')
        logger.warning(str(e))
        return e
    # following are the core RPC functions
    interfaces = {
                  'convert': oser.convert,
                  'upload': oser.upload,
                  'join': oser.join,
                 }
    
    app = JsonRpcApplication(rpcs = interfaces)
    http = None
    try:
        httpd = make_server(args.interface, args.port, app)
    except OSError as e:
        if e.errno == 98:
            logger.info('...failed')
            logger.warning('Address allready in use, %s:%s is occupied.' 
                % (args.interface, args.port))
            logger.warning("Seems like Aeroo DOCS allready running!")
        sys.exit()
    logger.info('...started')
    if not args.no_daemon:
        logger.removeHandler(stdout)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt as e:
        logger.info('Aeroo DOCS process interrupted.')
        sys.exit()


def start_daemon(args):
    logger.info('Starting Aeroo DOCS process...')
    #### Prepare spool directory
    if not os.path.exists(args.spool_directory):
        os.mkdir(args.spool_directory, mode=0o0700)
    daemon = False
    try:
        if args.no_daemon:
            main()
        else:
            daemon = Daemonize(app="aeroo_docs", pid=args.pid_file, action=main, keep_fds=PRESERVE_FH)
    except Exception as e:
        logger.info('...failed')
        raise daemon
        sys.exit()
    if isinstance(daemon, Exception):
        sys.exit()
    daemon and daemon.start()

def stop_daemon(args):
    try:
        with open(args.pid_file, "r") as tmpfile:
            pid = int(tmpfile.read())
    except FileNotFoundError as e:
        logger.warning('Process allready stopped. Nothing to do...')
        return None
    tries = 0
    while tries < 10:
        if tries == 0:
            logger.info('Stopping Aeroo DOCS process...')
        try:
            os.kill(pid, SIGQUIT)
        #except ProcessLookupError as e:
        except OSError as e:
            if tries == 0:
                logger.warning('Not running...')
            else:
                logger.info('...stopped')
            logger.info('Removing pid file...')
            os.remove(args.pid_file)
            return None
        tries += 1
        sleep(1)

def restart_daemon(args):
    stop_daemon(args)
    start_daemon(args)

cmds = OrderedDict([
        ('start', start_daemon),
        ('stop', stop_daemon),
        ('restart', restart_daemon),
        ])


arg_parser = ArgumentParser(description='Converts and merges documents.')

arg_parser.add_argument('-c', '--config-file', type=str,
                    help="Read configuration from file.")
arg_parser.add_argument('-n', '--no-daemon', action='store_true',
                    help="Do not run as daemon.")
arg_parser.add_argument('-t', '--no-cleanup', action='store_true',
                    help="Do not perform clean up for spool directory.")
arg_parser.add_argument('-s', '--simple-auth', action='store_true',
                    help="Simple (username & password) authentication mode.")
arg_parser.add_argument('-u', '--username', type=str,
                    help="Username for the service. Use with --simple-auth.")
arg_parser.add_argument('-p', '--password', type=str,
                    help="Password for the service. Use with --simple-auth.")
arg_parser.add_argument('command', choices=cmds.keys(),
                    help="Run/Start/Stop/Restart Service.")

args = arg_parser.parse_args()


conf = '''
[start]
interface = localhost
port = 8989
oo-server = localhost
oo-port = 8100
spool-directory = /var/spool/aeroo-docs
spool-expire = 1800
log-file = /var/log/aeroo-docs.log
pid-file = /var/run/aeroo-docs.pid
[simple-auth]
username = anonymous
password = anonymous
'''

config = ConfigParser()
config.read_string(conf)

if args.config_file:
    if not os.path.exists(args.config_file):
        print('Error! Cannot read config file: %s' % args.config_file)
        sys.exit(1)
    config.read(args.config_file)

def update_args(conf, args):
    '''Updates ArgumentParser args from ConfigParser section.'''
    for k, v in conf.items():
        arg = k.replace('-', '_')
        val = getattr(args, arg, None)
        if val is None:
            #FIXME: Type conversion.
            try:
                val = int(v)
            except ValueError:
                val = v
            setattr(args, arg, val)

update_args(config['start'], args)

if args.simple_auth:
    update_args(config['simple-auth'], args)

if args.spool_directory:
    SPOOL_PATH = args.spool_directory + '/%s'


logger = logging.getLogger('main')
logger.setLevel(logging.DEBUG)
format = '%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
formatter = logging.Formatter(format)

if args.log_file:
    if not os.path.exists(args.log_file):
        log_dir = os.path.dirname(args.log_file)
        if not os.path.exists(log_dir):
            os.mkdir(log_dir, mode=0o0700)
    filehandler = logging.FileHandler(args.log_file)
    PRESERVE_FH.append(filehandler.stream.fileno())
    filehandler.setLevel(logging.DEBUG)
    filehandler.setFormatter(formatter)
    logger.addHandler(filehandler)

stdout = logging.StreamHandler(sys.stdout)
stdout.setLevel(logging.DEBUG)
mesformatter = logging.Formatter('%(message)s')
stdout.setFormatter(mesformatter)
logger.addHandler(stdout)


cmds[args.command](args)

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
