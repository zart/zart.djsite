'appcmd command'
import sys
import os
import shutil
import codecs
import ctypes
from subprocess import Popen, PIPE, list2cmdline
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext_lazy as _
from django.utils.module_loading import import_string


class RecodeStream(object):
    'Recoding stream wrapper'

    def __init__(self, buffer, data_encoding=None, file_encoding=None):
        'Convert incoming data to stream from data to file encoding'
        self.buffer = buffer
        self.data_encoding = data_encoding
        self.file_encoding = None
        if buffer.encoding is None:
            self.file_encoding = file_encoding or sys.getfilesystemencoding()

    def write(self, buf):
        'Perform recode'
        if not isinstance(buf, u''.__class__):  # this MUST be u''.__class__
            buf = buf.decode(self.data_encoding)
        if self.file_encoding:
            buf = buf.encode(self.file_encoding)
        self.buffer.write(buf)

    def __getattr__(self, name):
        'Proxy attribute access to wrapped stream'
        return getattr(self.buffer, name)


sys.stdout = RecodeStream(sys.__stdout__, 'utf-8')
sys.stderr = RecodeStream(sys.__stderr__, 'utf-8')


try:
    codecs.lookup('oem')  # added in py3.6+
    oemencoding = 'oem'
except Exception:
    oemencoding = 'cp%d' % ctypes.windll.kernel32.GetOEMCP()


def module_path(name):
    'Returns file path of python module'
    return import_string(name + '.__file__')


def quote(x):
    'Quote name'
    return '&quot;%s&quot;' % x if ' ' in x else x


def pdict(prefix='', **options):
    return '{}[{}]'.format(
        prefix, ','.join("{}='{}'".format(k, v) for k, v in options.items())
    )


def plist(*args):
    return '.'.join(
        pdict(**arg) if isinstance(arg, dict) else arg for arg in args
    )


def _asbool(x):
    'Convert string value to boolean'
    if not x:
        return None
    return str(x).lower() not in ['0', 'off', 'no', 'false']


class AppCmd(object):
    appcmd = 'appcmd.exe'
    config = None

    def __init__(self, appcmd=None, config=None):
        if appcmd:
            self.appcmd = appcmd
        if config:
            self.config = config

    def __repr__(self):
        cmd = [self.appcmd]
        if self.config:
            cmd.append('/apphostconfig:' + self.config)
        return '<AppCmd %r>' % cmd

    def __call__(self, *args, **options):
        xfail = options.pop('_xfail', None)
        cmd = [self.appcmd]
        if self.config:
            cmd.append('/apphostconfig:' + self.config)
        cmd.extend(args)
        cmd.extend(
            '/{}:{}'.format(k, v)
            for k, v in options.items()
            if not k.startswith('_')
        )
        proc = Popen(cmd, stdout=PIPE)
        out, err = proc.communicate()
        fail = proc.returncode != 0 or out.startswith(b'ERROR ')
        return fail, xfail, list2cmdline(cmd), out.decode(oemencoding)

    def lock(self, section):
        return self('lock', 'config', section=section)

    def unlock(self, section):
        return self('unlock', 'config', section=section)

    def cfg(self, *args, **options):
        return self('set', 'config', *args, **options)

    def fastcgi(
        self,
        handler='FastCGI-python',
        fullPath='',
        arguments='',
        env=None,
        params=None,
    ):
        if not fullPath:
            fullPath = sys.executable
        if not params:
            params = {}

        key = dict(fullPath=fullPath, arguments=arguments)

        out = []
        out.append(
            self.cfg(
                pdict('/-', **key),
                section='fastcgi',
                commit='apphost',
                _xfail=True,
            )
        )
        out.append(
            self.cfg(
                pdict('/+', **dict(key, **params)),
                *[
                    plist(
                        pdict('/+', **key),
                        'environmentVariables',
                        pdict(name=name, value=value),
                    )
                    for name, value in env.items()
                ],
                section='fastcgi',
                commit='apphost'
            )
        )
        return out

    def handler_del(self, appname, name, **options):
        return self.cfg(
            appname, pdict('/-', name=name), section='handlers', **options
        )

    def handler_add(self, appname, name, params=None, **options):
        if not params:
            params = {}
            # path='*',
            # verb='*',
            # modules='FastCgiModule',
            # scriptProcessor='|'.join([fullPath, arguments]),
            # resourceType='Unspecified',
            # requireAccess='Script',

        return self.cfg(
            appname,
            pdict('/+', name=name, **params),
            section='handlers',
            **options
        )

    def vdir(self, appname, path, physicalPath):
        out = []
        out.append(
            self('delete', 'vdir', '/vdir.name:' + appname + path, _xfail=True)
        )
        out.append(
            self(
                'add',
                'vdir',
                '/app.name:' + appname,
                path='/' + path,
                physicalPath=physicalPath,
            )
        )
        return out

    def auth(self, appname, winauth, **options):
        out = []
        out.append(
            self.cfg(
                appname,
                section='anonymousAuthentication',
                enabled='false' if winauth else 'true',
                **options
            )
        )
        out.append(
            self.cfg(
                appname,
                section='windowsAuthentication',
                enabled='true' if winauth else 'false',
                **options
            )
        )
        return out


class Command(BaseCommand):
    'Configure IIS (Express) with appcmd.'
    help = __doc__
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            '-32',
            dest='bits32',
            action='store_true',
            default=_asbool(os.getenv('IIS_32BIT'))
            or getattr(settings, 'IIS_32BIT', False),
            help=_('Use 32-bit IIS Express (default: %(default)s).'),
        )
        # use system-wide IIS or user IIS Express
        parser.add_argument(
            '-e',
            '--express',
            dest='express',
            action='store_true',
            default=_asbool(os.getenv('IIS_EXPRESS'))
            or getattr(settings, 'IIS_EXPRESS', True),
            help=_('Use IIS Express instead of IIS (default: %(default)s).'),
        )
        parser.add_argument(
            '--site',
            default=os.getenv('IIS_SITE_NAME')
            or getattr(settings, 'IIS_SITE_NAME', 'Website1'),
            help=_('IIS site name to run (default: "%(default)s").'),
        )
        # hidden option
        parser.add_argument(
            '--home',
            default=os.getenv('IIS_USER_HOME')
            or getattr(settings, 'IIS_USER_HOME', '.'),
            help=_('IIS configuration directory (default: "%(default)s").'),
        )
        parser.add_argument(
            '--fastcgi',
            default=getattr(settings, 'IIS_FASTCGI', 'FastCGI-Python'),
            help=_('FastCGI handler name (default: "%(default)s)".'),
        )

    def handle(self, *args, **options):
        'Perform command'
        verbose = options['verbosity']  # 0 quiet, 1 normal, 2 verbose, 3 trace
        bits32 = options['bits32']
        site = options['site']
        iis_user_home = options['home']
        iis_handler = options['fastcgi']
        write = self.stdout.write

        program_files = (
            os.getenv('ProgramFiles', r'C:\Program Files')
            if not bits32
            else os.getenv('ProgramFiles(x86)', r'C:\Program Files(x86)')
        )
        iis_bin = os.path.join(program_files, 'IIS Express')
        appcmd_exe = os.path.join(iis_bin, 'appcmd.exe')
        configdir = os.path.join(iis_user_home, 'config')
        config = os.path.join(configdir, 'applicationhost.config')

        if sys.platform != 'win32':
            raise CommandError(
                _('Platform "%s" is not supported.') % sys.platform
            )
        if not os.path.exists(appcmd_exe):
            raise CommandError(
                _(
                    'Executable "%s" does not exist. '
                    'Install IIS Express (http://aka.ms/iisexpress10).'
                )
                % appcmd_exe
            )

        try:
            module_path('wfastcgi')
        except ImportError:
            raise CommandError(
                _('Module wfascgi not found. Run "pip install wfastcgi".')
            )

        if not os.path.isdir(configdir):
            tpldir = os.path.join(
                iis_bin, 'config', 'templates', 'PersonalWebServer'
            )
            if not os.path.isdir(tpldir):
                raise CommandError(
                    _(
                        'Directory "%s" does not exist. '
                        'Install IIS Express (http://aka.ms/iisexpress10).'
                    )
                    % tpldir
                )

            if verbose > 0:
                write(_('Copy template config directory.'), self.style.WARNING)
            shutil.copytree(tpldir, configdir)
        if not os.path.exists(config):
            raise CommandError(
                _('Configuration file "%s" does not exist.') % config
            )

        def call(result):
            abort = False
            if not isinstance(result, list):
                result = [result]
            for res in result:
                fail, xfail, cmdline, output = res
                if verbose > 1:
                    write('Run: ' + cmdline, self.style.MIGRATE_HEADING)
                if verbose > 2:
                    style = self.style.SUCCESS
                    if fail:
                        if xfail:
                            style = self.style.WARNING
                        else:
                            style = self.style.ERROR
                            abort = True
                    write(output, style)
            if abort:
                raise CommandError

        dsm = os.getenv('DJANGO_SETTINGS_MODULE')
        fullPath = sys.executable
        arguments = '-u -m wfastcgi'
        # arguments = '-u ' + quote(wfastcgi)

        env = {}
        env['DJANGO_SETTINGS_MODULE'] = dsm
        env['WSGI_HANDLER'] = settings.WSGI_APPLICATION
        env['WSGI_LOG'] = os.path.abspath('wsgi.log')

        params = dict(
            # 10-3600, IIS 7.0: 30, IIS 7.5: 70
            # activityTimeout=70,
            activityTimeout=10,
            # boolean
            # flushNamedPipe='false',
            # 10-604800, 300
            # idleTimeout=300,
            idleTimeout=10,
            # 1-10000000, 200
            # instanceMaxRequests=200,
            instanceMaxRequests=10,
            # 0-10000, 0
            # maxInstances=0,
            # path, IIS 7.5+
            monitorChangesTo=module_path(dsm),
            # NamedPipe/Tcp
            # protocol='NamedPipe',
            # 1-10000000, 1000
            # queueLength=1000,
            # 10-604800, 90
            # requestTimeout=90,
            # IIS 7.5+: 0
            # signalBeforeTerminateSeconds=0,
            # ReturnStdErrIn500/ReturnGeneric500/IgnoreAndReturn200/TerminateProcess
            # stderrMode='ReturnStdErrIn500',
        )

        appname = site + '/'
        appcmd = AppCmd(appcmd_exe, os.path.abspath(config))
        call(appcmd.unlock('anonymousAuthentication'))
        call(appcmd.unlock('windowsAuthentication'))
        call(appcmd.fastcgi(arguments=arguments, params=params, env=env))
        call(
            appcmd.handler_del(
                appname, iis_handler, commit='apphost', _xfail=True
            )
        )
        call(
            appcmd.handler_add(
                appname,
                iis_handler,
                params=dict(
                    path='*',
                    verb='*',
                    modules='FastCgiModule',
                    scriptProcessor='|'.join([fullPath, arguments]),
                    resourceType='Unspecified',
                    requireAccess='Script',
                ),
                commit='apphost',
            )
        )
        call(appcmd.auth(site + '/', True, commit='apphost'))

        if settings.STATIC_URL and settings.STATIC_ROOT:
            appname = site + '/'
            path = settings.STATIC_URL.strip('/')
            physicalPath = os.path.abspath(settings.STATIC_ROOT)
            call(appcmd.vdir(appname, path, physicalPath))
            call(appcmd.handler_del(appname + path, iis_handler, _xfail=True))
            call(appcmd.auth(appname + path, False))

        if settings.MEDIA_URL and settings.MEDIA_ROOT:
            appname = site + '/'
            path = settings.MEDIA_URL.strip('/')
            physicalPath = os.path.abspath(settings.MEDIA_ROOT)
            call(appcmd.vdir(appname, path, physicalPath))
            call(appcmd.handler_del(appname + path, iis_handler, _xfail=True))
            call(appcmd.auth(appname + path, False))
