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
        if not isinstance(buf, u''.__class__):
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
    codecs.lookup('oem')
    oemencoding = 'oem'
except Exception:
    oemencoding = 'cp%d' % ctypes.windll.kernel32.GetOEMCP()


def module_path(name):
    'Returns file path of python module'
    return import_string(name + '.__file__')


def quote(x):
    'Quote name'
    return '&quot;%s&quot;' % x if ' ' in x else x


def paramdict(prefix='', **options):
    return '{}[{}]'.format(
        prefix, ','.join("{}='{}'".format(k, v) for k, v in options.items())
    )


def paramlist(*args):
    return '.'.join(
        paramdict(**arg) if isinstance(arg, dict) else arg for arg in args
    )


def _asbool(x):
    'Convert string value to boolean'
    if not x:
        return None
    return str(x).lower() not in ['0', 'off', 'no', 'false']


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
            wfastcgi = module_path('wfastcgi')
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
            shutil.copytree(tpldir, configdir, dirs_exist_ok=True)
        if not os.path.exists(config):
            raise CommandError(
                _('Configuration file "%s" does not exist.') % config
            )

        appcmd = (appcmd_exe, '/apphostconfig:' + os.path.abspath(config))

        dsm = os.getenv('DJANGO_SETTINGS_MODULE')
        fullPath = sys.executable
        # arguments = '-u ' + quote(wfastcgi)
        arguments = '-u -m wfastcgi'

        iise_envvars = {
            'DJANGO_SETTINGS_MODULE': dsm,
            'WSGI_HANDLER': settings.WSGI_APPLICATION,
        }

        def _cmd(*cmd, failok=False):
            cmd = appcmd + cmd
            if verbose > 1:
                write('Run: ' + list2cmdline(cmd), self.style.MIGRATE_HEADING)
            proc = Popen(cmd, stdout=PIPE)
            out, err = proc.communicate()
            if verbose > 2:
                if out.startswith(b'ERROR'):
                    if failok:
                        style = self.style.WARNING
                    else:
                        style = self.style.ERROR
                else:
                    style = self.style.SUCCESS
                write(out.decode(oemencoding), style)

        params = dict(fullPath=fullPath, arguments=arguments)
        fullparams = dict(
            params,
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

        _cmd(
            'set',
            'config',
            '/section:fastCgi',
            '/-' + paramdict(**params),
            '/commit:apphost',
            failok=True,
        )

        _cmd(
            'set',
            'config',
            '/commit:apphost',
            '/section:fastCgi',
            '/+' + paramdict(**params),
            *[
                '/+'
                + paramlist(
                    params,
                    'environmentVariables',
                    paramdict(name=name, value=value),
                )
                for name, value in iise_envvars.items()
            ]
        )

        _cmd(
            'set',
            'config',
            '/section:handlers',
            '/' + paramdict('-', name=iis_handler),
            '/commit:apphost',
            failok=True,
        )

        _cmd(
            'set',
            'config',
            '/section:handlers',
            '/'
            + paramdict(
                '+',
                name=iis_handler,
                path='*',
                verb='*',
                modules='FastCgiModule',
                scriptProcessor='|'.join([fullPath, arguments]),
                resourceType='Unspecified',
                requireAccess='Script',
            ),
            '/commit:apphost',
        )

        appname = site + '/admin/login/'

        _cmd('unlock', 'config', '/section:anonymousAuthentication')
        _cmd('unlock', 'config', '/section:windowsAuthentication')

        _cmd(
            'set',
            'config',
            appname,
            '/section:anonymousAuthentication',
            '/enabled:false',
            '/commit:apphost',
        )

        _cmd(
            'set',
            'config',
            appname,
            '/section:windowsAuthentication',
            '/enabled:true',
            '/commit:apphost',
        )

        if settings.STATIC_URL and settings.STATIC_ROOT:
            appname = site + '/' + settings.STATIC_URL.strip('/')
            _cmd('delete', 'vdir', '/vdir.name:' + appname, failok=True)

            _cmd(
                'add',
                'vdir',
                '/app.name:' + site + '/',
                '/path:' + '/' + settings.STATIC_URL.strip('/'),
                '/physicalPath:' + os.path.abspath(settings.STATIC_ROOT),
            )

            _cmd(
                'set',
                'config',
                appname,
                '/section:handlers',
                '/-' + paramdict(name=iis_handler),
                failok=True,
            )

            _cmd(
                'set',
                'config',
                appname,
                '/section:anonymousAuthentication',
                '/enabled:true',
            )

            _cmd(
                'set',
                'config',
                appname,
                '/section:windowsAuthentication',
                '/enabled:false',
            )

        if settings.MEDIA_URL and settings.MEDIA_ROOT:
            appname = site + '/' + settings.MEDIA_URL.strip('/')
            _cmd('delete', 'vdir', '/vdir.name:' + appname, failok=True)

            _cmd(
                'add',
                'vdir',
                '/app.name:' + site + '/',
                '/path:' + '/' + settings.STATIC_URL.strip('/'),
                '/physicalPath:' + os.path.abspath(settings.STATIC_ROOT),
            )

            _cmd(
                'set',
                'config',
                appname,
                '/section:handlers',
                '/-' + paramdict(name=iis_handler),
            )

            _cmd(
                'set',
                'config',
                appname,
                '/section:anonymousAuthentication',
                '/enabled:true',
            )

            _cmd(
                'set',
                'config',
                appname,
                '/section:windowsAuthentication',
                '/enabled:false',
            )

