'iisexpress command'
import sys
import os
from subprocess import Popen, PIPE, STDOUT, list2cmdline
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext_lazy as _


class RecodeStream(object):
    'Recoding stream wrapper'

    def __init__(self, buffer, data_encoding=None, file_encoding=None):
        'Convert incoming data to stream from data to file encoding'
        if file_encoding is None:
            file_encoding = sys.getfilesystemencoding()
        file_encoding = None
        self.buffer = buffer
        self.data_encoding = data_encoding
        self.file_encoding = None
        if buffer.encoding is None:
            self.file_encoding = file_encoding

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

PY2 = sys.version_info[0] < 3


def _asbool(x):
    'Convert string value to boolean'
    if not x:
        return None
    return str(x).lower() not in ['0', 'off', 'no', 'false']


class Command(BaseCommand):
    'Starts IIS Express webserver for development and serves static files.'
    help = __doc__
    requires_migrations_checks = True
    stealth_options = ('home',)

    def add_arguments(self, parser):
        parser.add_argument(
            '-32',
            dest='bits32',
            action='store_true',
            default=_asbool(os.getenv('IIS_32BIT'))
            or getattr(settings, 'IIS_32BIT', False),
            help=_('Use 32-bit IIS Express (default: %(default)s).'),
        )
        parser.add_argument(
            '--site',
            default=os.getenv('IIS_SITE_NAME')
            or getattr(settings, 'IIS_SITE_NAME', 'Website1'),
            help=_('IIS site name to run (default: %(default)s).'),
        )
        # hidden option
        parser.add_argument(
            '--home',
            default=os.getenv('IIS_USER_HOME')
            or getattr(settings, 'IIS_USER_HOME', '.'),
            help=_('IIS configuration directory (default: %(default)s).'),
        )

    def handle(self, *args, **options):
        'Perform command'
        verbose = options['verbosity']  # 0 quiet, 1 normal, 2 verbose, 3 trace
        bits32 = options['bits32']
        site = options['site']
        iis_user_home = options['home']
        write, flush = self.stdout.write, self.stdout.flush

        # variables
        # environment might be empty (hello, tox), so provide defaults
        program_files = (
            os.getenv('ProgramFiles', r'C:\Program Files')
            if not bits32
            else os.getenv('ProgramFiles(x86)', r'C:\Program Files(x86)')
        )
        iis_bin = os.path.join(program_files, 'IIS Express')
        iis_exe = os.path.join(iis_bin, 'iisexpress.exe')

        if sys.platform != 'win32':
            raise CommandError(
                _('Platform "%s" is not supported.') % sys.platform
            )
        if not os.path.exists(iis_exe):
            raise CommandError(
                _(
                    'Executable "%s" does not exist. '
                    'Install IIS Express (http://aka.ms/iisexpress10).'
                )
                % iis_exe
            )

        # command line
        cmd = [iis_exe, '/userhome:' + iis_user_home]
        if site:
            cmd += ['/site:' + site]
        if verbose > 2:
            cmd += ['/trace:info']

        # report
        if verbose > 1:
            write('IIS_32BIT     : ' + str(bits32))
            write('IIS_BIN       : ' + iis_bin)
            write('IIS_USER_HOME : ' + iis_user_home)

        if verbose > 1:
            write(_('Running: %s') % (list2cmdline(cmd),))

        # run IIS Express, disable buffering and read line by line
        # NOTE: sadly, encoding='mbcs' is py3k
        proc = Popen(cmd, stdout=PIPE, stderr=STDOUT, bufsize=0)
        try:
            # on python 2.0 use readline(). see bpo-3907
            stdout = iter(proc.stdout.readline, b'') if PY2 else proc.stdout
            for line in stdout:
                line = line.decode('mbcs').rstrip()

                # apply style
                style = None
                if 'HTTP status 5' in line:
                    style = self.style.HTTP_SERVER_ERROR
                elif 'HTTP status 404' in line:
                    style = self.style.HTTP_NOT_FOUND
                elif 'HTTP status 4' in line:
                    style = self.style.HTTP_BAD_REQUEST
                elif 'HTTP status 304' in line:
                    style = self.style.HTTP_NOT_MODIFIED
                elif 'HTTP status 3' in line:
                    style = self.style.HTTP_REDIRECT
                elif 'HTTP status 2' in line:
                    style = self.style.HTTP_SUCCESS
                elif 'HTTP status 1' in line:
                    style = self.style.HTTP_INFO
                elif 'IIS Express' in line:
                    style = self.style.NOTICE

                if verbose > 0:
                    write(line, style)
                    flush()
            proc.stdout.close()
            proc.wait()
            if verbose > 1:
                write(_('Return code: 0x{:08x}').format(proc.returncode))
            if verbose > 0:
                write(_('Done'), self.style.SUCCESS)
        finally:
            if proc.returncode is None:
                proc.kill()
