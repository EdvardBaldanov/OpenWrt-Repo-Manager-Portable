#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""
   Utility to create opkg compatible indexes
"""
from __future__ import absolute_import
from __future__ import print_function

import sys
import os
import tarfile
import tempfile
import hashlib
import re
import subprocess
from stat import ST_SIZE
import collections
import argparse
import posixpath

# ==============================================================================
# arfile.py content
# ==============================================================================

class FileSection(object):
    "A class which allows to treat portion of file as separate file object."

    def __init__(self, f, offset, size):
        self.f = f
        self.offset = offset
        self.size = size
        self.seek(0, 0)

    def seek(self, offset, whence=0):
        if whence == 0:
            return self.f.seek(offset + self.offset, whence)
        elif whence == 1:
            return self.f.seek(offset, whence)
        elif whence == 2:
            return self.f.seek(self.offset + self.size + offset, 0)
        else:
            assert False

    def seekable(self):
        return True

    def tell(self):
        return self.f.tell() - self.offset

    def read(self, size=-1):
        return self.f.read(size)


class ArFile(object):

    def __init__(self, f, fn):
        self.f = f
        self.directory = {}
        self.directoryRead = False

        signature = self.f.readline()
        assert signature == "!<arch>\n" or signature == b"!<arch>\n", "Old ipk format (non-deb) is unsupported, file: %s, magic: %s, expected %s" % (fn, signature, "!<arch>")
        self.directoryOffset = self.f.tell()

    def open(self, fname):
        if fname in self.directory:
            return FileSection(self.f, self.directory[fname][-1], int(self.directory[fname][5]))

        if self.directoryRead:
            raise IOError("AR member not found: " + fname)

        f = self._scan(fname)
        if f is None:
            raise IOError("AR member not found: " + fname)
        return f

    def _scan(self, fname):
        self.f.seek(self.directoryOffset, 0)

        while True:
            line = self.f.readline()
            if not line:
                self.directoryRead = True
                return None

            if line.decode('ascii') == "\n":
                line = self.f.readline()
                if not line:
                    break
            line = line.decode('ascii')
            line = line.replace('`', '')
            # Field lengths from /usr/include/ar.h:
            ar_field_lens = [16, 12, 6, 6, 8, 10, 2]
            descriptor = []
            for field_len in ar_field_lens:
                descriptor.append(line[:field_len].strip())
                line = line[field_len:]
            size = int(descriptor[5])
            # Check for optional / terminator
            if descriptor[0][-1] == "/":
                memberName = descriptor[0][:-1]
            else:
                memberName = descriptor[0]
            self.directory[memberName] = descriptor + [self.f.tell()]

            if memberName == fname:
                # Record directory offset to start from next time
                self.directoryOffset = self.f.tell() + size
                return FileSection(self.f, self.f.tell(), size)

            # Skip data and loop
            if size % 2:
                size = size + 1
            data = self.f.seek(size, 1)

# ==============================================================================
# opkg.py content
# ==============================================================================

def order(x):
    if not x:
        return 0
    if x == "~":
        return -1
    if str.isdigit(x):
        return 0
    if str.isalpha(x):
        return ord(x)

    return 256 + ord(x)


class Version(object):
    """A class for holding parsed package version information."""

    def __init__(self, epoch, version):
        self.epoch = epoch
        self.version = version

    def _versioncompare(self, selfversion, refversion):
        """
                Implementation below is a copy of the opkg version comparison algorithm
                http://git.yoctoproject.org/cgit/cgit.cgi/opkg/tree/libopkg/pkg.c*n933
                it alternates between number and non number comparisons until a difference is found
                digits are compared by value. other characters are sorted lexically using the above method orderOfChar

                One slight modification, the original version can return any value, whereas this one is limited to -1, 0, +1
                """
        if not selfversion:
            selfversion = ""
        if not refversion:
            refversion = ""

        value = list(selfversion)
        ref = list(refversion)

        while value or ref:
            first_diff = 0
            # alphanumeric comparison
            while (value and not str.isdigit(value[0])) or (ref and not str.isdigit(ref[0])):
                vc = order(value.pop(0) if value else None)
                rc = order(ref.pop(0) if ref else None)
                if vc != rc:
                    return -1 if vc < rc else 1

            # comparing numbers
            # start by skipping 0
            while value and value[0] == "0":
                value.pop(0)
            while ref and ref[0] == "0":
                ref.pop(0)

            # actual number comparison
            while value and str.isdigit(value[0]) and ref and str.isdigit(ref[0]):
                if not first_diff:
                    first_diff = int(value.pop(0)) - int(ref.pop(0))
                else:
                    value.pop(0)
                    ref.pop(0)

            # the one that has a value remaining was the highest number
            if value and str.isdigit(value[0]):
                return 1
            if ref and str.isdigit(ref[0]):
                return -1
            # in case of equal length numbers look at the first diff
            if first_diff:
                return 1 if first_diff > 0 else -1
        return 0

    def compare(self, ref):
        if (self.epoch > ref.epoch):
            return 1
        elif (self.epoch < ref.epoch):
            return -1
        else:
            self_ver_comps = re.match(r"(.+?)(-r.+)?$", self.version)
            ref_ver_comps = re.match(r"(.+?)(-r.+)?$", ref.version)
            r = self._versioncompare(self_ver_comps.group(1), ref_ver_comps.group(1))
            if r == 0:
                r = self._versioncompare(self_ver_comps.group(2), ref_ver_comps.group(2))
            return r

    def __str__(self):
        return str(self.epoch) + ":" + self.version


def parse_version(versionstr):
    epoch = 0
    # check for epoch
    m = re.match('([0-9]*):(.*)', versionstr)
    if m:
        (epochstr, versionstr) = m.groups()
        epoch = int(epochstr)
    return Version(epoch, versionstr)


class Package(object):
    """A class for creating objects to manipulate (e.g. create) opkg
       packages."""

    # fn: Package file path
    # relpath: If this argument is set, the file path is given relative to this
    #   path when a string representation of the Package object is created. If
    #   this argument is not set, the basename of the file path is given.
    def __init__(self, fn=None, relpath=None, all_fields=None):
        self.package = None
        self.version = 'none'
        self.parsed_version = None
        self.architecture = None
        self.maintainer = None
        self.source = None
        self.description = None
        self.depends = None
        self.provides = None
        self.replaces = None
        self.conflicts = None
        self.recommends = None
        self.suggests = None
        self.section = None
        self.filename_header = None
        self.file_list = []
        self.installed_size = None
        self.filename = None
        self.file_ext_opk = "ipk"
        self.homepage = None
        self.oe = None
        self.priority = None
        self.tags = None
        self.fn = fn
        self.license = None

        self.user_defined_fields = collections.OrderedDict()
        if fn:
            # see if it is deb format
            f = open(fn, "rb")

            if relpath:
                self.filename = os.path.relpath(fn, relpath)
            else:
                self.filename = os.path.basename(fn)

            if tarfile.is_tarfile(fn):
                tar = tarfile.open(fn, "r", f)
                tarStream = tar.extractfile("./control.tar.gz")
            else:
                ar = ArFile(f, fn)
                tarStream = ar.open("control.tar.gz")
            tarf = tarfile.open("control.tar.gz", "r", tarStream)
            try:
                control = tarf.extractfile("control")
            except KeyError:
                control = tarf.extractfile("./control")
            try:
                self.read_control(control, all_fields)
            except TypeError as e:
                sys.stderr.write("Cannot read control file '%s' - %s\n" % (fn, e))
            control.close()
        self.scratch_dir = None
        self.file_dir = None
        self.meta_dir = None

    def __getattr__(self, name):
        if name == "md5":
            self._computeFileMD5()
            return self.md5
        elif name == "sha256":
            self._computeFileSHA256()
            return self.sha256
        elif name == 'size':
            return self._get_file_size()
        else:
            raise AttributeError(name)

    def _computeFileMD5(self):
        # compute the MD5.
        if not self.fn:
            self.md5 = 'Unknown'
        else:
            f = open(self.fn, "rb")
            sum = hashlib.md5()
            while True:
                data = f.read(1024)
                if not data:
                    break
                sum.update(data)
            f.close()
            self.md5 = sum.hexdigest()

    def _computeFileSHA256(self):
        # compute the SHA256.
        if not self.fn:
            self.sha256 = 'Unknown'
        else:
            f = open(self.fn, "rb")
            sum = hashlib.sha256()
            while True:
                data = f.read(1024)
                if not data:
                    break
                sum.update(data)
            f.close()
            self.sha256 = sum.hexdigest()

    def _get_file_size(self):
        if not self.fn:
            self.size = 0
        else:
            stat = os.stat(self.fn)
            self.size = stat[ST_SIZE]
        return int(self.size)

    def read_control(self, control, all_fields=None):
        line = control.readline()
        while 1:
            if not line:
                break
            # Decode if stream has byte strings
            if not isinstance(line, str):
                line = line.decode()
            line = line.rstrip()
            lineparts = re.match(r'([\w-]*?):\s*(.*)', line)
            if lineparts:
                name = lineparts.group(1)
                name_lowercase = name.lower()
                value = lineparts.group(2)
                while 1:
                    line = control.readline().rstrip()
                    if not line:
                        break
                    if line[0] != ' ':
                        break

                    value = value + '\n' + line
                if name_lowercase == 'size':
                    self.size = int(value)
                elif name_lowercase == 'md5sum':
                    self.md5 = value
                elif name_lowercase == 'sha256sum':
                    self.sha256 = value
                elif name_lowercase in self.__dict__:
                    self.__dict__[name_lowercase] = value
                elif all_fields:
                    self.user_defined_fields[name] = value
                else:
                    print("Lost field %s, %s" % (name,value))
                    pass

                if line and line[0] == '\n':
                    return  # consumes one blank line at end of package description
            else:
                line = control.readline()
                pass
        return

    def _setup_scratch_area(self):
        self.scratch_dir = "%s/%sopkg" % (tempfile.gettempdir(), tempfile.gettempprefix())
        self.file_dir = "%s/files" % (self.scratch_dir)
        self.meta_dir = "%s/meta" % (self.scratch_dir)

        os.mkdir(self.scratch_dir)
        os.mkdir(self.file_dir)
        os.mkdir(self.meta_dir)

    def set_package(self, package):
        self.package = package

    def get_package(self):
        return self.package

    def set_version(self, version):
        self.version = version
        self.parsed_version = parse_version(version)

    def get_version(self):
        return self.version

    def set_architecture(self, architecture):
        self.architecture = architecture

    def get_architecture(self):
        return self.architecture

    def set_maintainer(self, maintainer):
        self.maintainer = maintainer

    def get_maintainer(self):
        return self.maintainer

    def set_source(self, source):
        self.source = source

    def get_source(self):
        return self.source

    def set_description(self, description):
        self.description = description

    def get_description(self):
        return self.description

    def set_depends(self, depends):
        self.depends = depends

    def get_depends(self, depends):
        return self.depends

    def set_provides(self, provides):
        self.provides = provides

    def get_provides(self, provides):
        return self.provides

    def set_replaces(self, replaces):
        self.replaces = replaces

    def get_replaces(self, replaces):
        return self.replaces

    def set_conflicts(self, conflicts):
        self.conflicts = conflicts

    def get_conflicts(self, conflicts):
        return self.conflicts

    def set_suggests(self, suggests):
        self.suggests = suggests

    def get_suggests(self, suggests):
        return self.suggests

    def set_section(self, section):
        self.section = section

    def get_section(self, section):
        return self.section

    def set_license(self, license):
        self.license = license

    def get_license(self, license):
        return self.license

    def get_file_list_dir(self, directory):
        def check_output(*popenargs, **kwargs):
            """Run command with arguments and return its output as a byte string.

            Backported from Python 2.7 as it's implemented as pure python on stdlib.

            >>> check_output(['/usr/bin/python', '--version'])
            Python 2.6.2
            """
            process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
            output, unused_err = process.communicate()
            retcode = process.poll()
            if retcode:
                cmd = kwargs.get("args")
                if cmd is None:
                    cmd = popenargs[0]
                error = subprocess.CalledProcessError(retcode, cmd)
                error.output = output
                raise error
            output = output.decode("utf-8")
            return output

        if not self.fn:
            try:
                cmd = "find %s -name %s | head -n 1" % (directory, self.filename)
                rc = check_output(cmd, shell=True)
                if rc != "":
                    newfn = str(rc).split()[0]
#                    sys.stderr.write("Package '%s' with empty fn and filename is '%s' was found in '%s', updating fn\n" % (self.package, self.filename, newfn))
                    self.fn = newfn
            except OSError as e:
                sys.stderr.write("Cannot find current fn for package '%s' filename '%s' in dir '%s'\n(%s)\n" % (self.package, self.filename, directory, e))
            except IOError as e:
                sys.stderr.write("Cannot find current fn for package '%s' filename '%s' in dir '%s'\n(%s)\n" % (self.package, self.filename, directory, e))
        return self.get_file_list()

    def get_file_list(self):
        if not self.fn:
            sys.stderr.write("Package '%s' has empty fn, returning empty filelist\n" % (self.package))
            return []
        f = open(self.fn, "rb")
        ar = ArFile(f, self.fn)
        try:
            tarStream = ar.open("data.tar.gz")
            tarf = tarfile.open("data.tar.gz", "r", tarStream)
        except IOError:
            tarStream = ar.open("data.tar.xz")
            tarf = tarfile.open("data.tar.xz", "r:xz", tarStream)
        self.file_list = tarf.getnames()
        self.file_list = [["./", ""][a.startswith("./")] + a for a in self.file_list]

        f.close()
        return self.file_list

    def set_package_extension(self, ext="ipk"):
        self.file_ext_opk = ext

    def get_package_extension(self):
        return self.file_ext_opk

    def write_package(self, dirname):
        self._setup_scratch_area()
        file = open("%s/control" % self.meta_dir, 'w')
        file.write(str(self))
        file.close()

        cmd = "cd %s ; tar cvz --format=gnu -f %s/control.tar.gz control" % (self.meta_dir, self.scratch_dir)

        cmd_out, cmd_in, cmd_err = os.popen3(cmd)

        while cmd_err.readline() != "":
            pass

        cmd_out.close()
        cmd_in.close()
        cmd_err.close()

        bits = "control.tar.gz"

        if self.file_list:
            cmd = "cd %s ; tar cvz --format=gnu -f %s/data.tar.gz" % (self.file_dir, self.scratch_dir)
            cmd_out, cmd_in, cmd_err = os.popen3(cmd)

            while cmd_err.readline() != "":
                pass

            cmd_out.close()
            cmd_in.close()
            cmd_err.close()

            bits = bits + " data.tar.gz"

        file = "%s_%s_%s.%s" % (self.package, self.version, self.architecture, self.get_package_extension())
        cmd = "cd %s ; tar cvz --format=gnu -f %s/%s %s" % (self.scratch_dir, dirname, file, bits)

        cmd_out, cmd_in, cmd_err = os.popen3(cmd)

        while cmd_err.readline() != "":
            pass

        cmd_out.close()
        cmd_in.close()
        cmd_err.close()

    def compare_version(self, ref):
        """Compare package versions of self and ref"""
        if not self.version:
            print('No version for package %s' % self.package)
        if not ref.version:
            print('No version for package %s' % ref.package)
        if not self.parsed_version:
            self.parsed_version = parse_version(self.version)
        if not ref.parsed_version:
            ref.parsed_version = parse_version(ref.version)
        return self.parsed_version.compare(ref.parsed_version)

    def print(self, checksum):
        out = ""

        # XXX - Some checks need to be made, and some exceptions
        #       need to be thrown. -- a7r

        if self.package:
            out = out + "Package: %s\n" % (self.package)
        if self.version:
            out = out + "Version: %s\n" % (self.version)
        if self.depends:
            out = out + "Depends: %s\n" % (self.depends)
        if self.provides:
            out = out + "Provides: %s\n" % (self.provides)
        if self.replaces:
            out = out + "Replaces: %s\n" % (self.replaces)
        if self.conflicts:
            out = out + "Conflicts: %s\n" % (self.conflicts)
        if self.suggests:
            out = out + "Suggests: %s\n" % (self.suggests)
        if self.recommends:
            out = out + "Recommends: %s\n" % (self.recommends)
        if self.section:
            out = out + "Section: %s\n" % (self.section)
        if self.architecture:
            out = out + "Architecture: %s\n" % (self.architecture)
        if self.maintainer:
            out = out + "Maintainer: %s\n" % (self.maintainer)
        if 'md5' in checksum:
            if self.md5:
                out = out + "MD5Sum: %s\n" % (self.md5)
        if 'sha256' in checksum:
            if self.sha256:
                out = out + "SHA256sum: %s\n" % (self.sha256)
        if self.size:
            out = out + "Size: %d\n" % int(self.size)
        if self.installed_size:
            out = out + "InstalledSize: %d\n" % int(self.installed_size)
        if self.filename:
            out = out + "Filename: %s\n" % (self.filename)
        if self.source:
            out = out + "Source: %s\n" % (self.source)
        if self.description:
            out = out + "Description: %s\n" % (self.description)
        if self.oe:
            out = out + "OE: %s\n" % (self.oe)
        if self.homepage:
            out = out + "HomePage: %s\n" % (self.homepage)
        if self.license:
            out = out + "License: %s\n" % (self.license)
        if self.priority:
            out = out + "Priority: %s\n" % (self.priority)
        if self.tags:
            out = out + "Tags: %s\n" % (self.tags)
        if self.user_defined_fields:
            for k, v in self.user_defined_fields.items():
                out = out + "%s: %s\n" % (k, v)
        out = out + "\n"

        return out

    def __del__(self):
        # XXX - Why is the `os' module being yanked out before Package objects
        #       are being destroyed?  -- a7r
        pass


class Packages(object):
    """A currently unimplemented wrapper around the opkg utility."""

    def __init__(self):
        self.packages = {}
        return

    def add_package(self, pkg, opt_a=0):
        package = pkg.package
        arch = pkg.architecture
        ver = pkg.version
        if opt_a:
            name = ("%s:%s:%s" % (package, arch, ver))
        else:
            name = ("%s:%s" % (package, arch))

        if (name not in self.packages):
            self.packages[name] = pkg

        if pkg.compare_version(self.packages[name]) >= 0:
            self.packages[name] = pkg
            return 0
        else:
            return 1

    def read_packages_file(self, fn, all_fields=None):
        f = open(fn, "r")
        while True:
            pkg = Package()
            try:
                pkg.read_control(f, all_fields)
            except TypeError as e:
                sys.stderr.write("Cannot read control file '%s' - %s\n" % (fn, e))
                continue
            if pkg.get_package():
                self.add_package(pkg)
            else:
                break
        f.close()
        return

    def write_packages_file(self, fn):
        f = open(fn, "w")
        names = list(self.packages.keys())
        names.sort()
        for name in names:
            f.write(self.packages[name].__str__())
        return

    def keys(self):
        return list(self.packages.keys())

    def __getitem__(self, key):
        return self.packages[key]

# ==============================================================================
# opkg-make-index content
# ==============================================================================

def to_morgue(filename, pkg_dir, verbose):
    """ Move files to morgue folder """
    morgue_dir = pkg_dir + "/morgue"
    if verbose:
        sys.stderr.write("Moving " + filename + " to morgue\n")
    if not os.path.exists(morgue_dir):
        os.mkdir(morgue_dir)
    if os.path.exists(pkg_dir + "/" + filename):
        os.rename(pkg_dir + "/" + filename, morgue_dir + "/" + filename)
    if os.path.exists(pkg_dir + "/" + filename + ".asc"):
        os.rename(pkg_dir + "/" + filename + ".asc", morgue_dir + "/" + filename + ".asc")


def to_locale(filename, locale, pkg_dir, locales_dir, verbose):
    """ Move file to locale_dir"""
    locale_dir = pkg_dir + '/' + locales_dir + '/' + locale + "/"
    if verbose:
        sys.stderr.write("Moving " + filename + " to " + locale_dir + "\n")
    if not os.path.exists(locale_dir):
        os.mkdir(locale_dir)
    os.rename(pkg_dir + "/" + filename, locale_dir + "/" + filename)
    if os.path.exists(pkg_dir + "/" + filename + ".asc"):
        os.rename(pkg_dir + "/" + filename + ".asc", locale_dir + "/" + filename + ".asc")


def make_index(pkg_dir, packages_filename=None, filelist_filename=None, old_filename=None, 
               locales_dir=None, verbose=False, opt_m=False, opt_a=False, opt_f=False, 
               opt_s=False, checksum=['md5']):
    """ Programmatic entry point for index creation """
    stamplist_filename = "Packages.stamps"
    if packages_filename:
        stamplist_filename = packages_filename + ".stamps"

    packages = Packages()

    old_pkg_hash = {}
    if packages_filename and not old_filename and os.path.exists(packages_filename):
        old_filename = packages_filename

    pkgs_stamps = {}
    if old_filename:
        if verbose:
            sys.stderr.write("Reading package list from " + old_filename + "\n")
        old_packages = Packages()
        old_packages.read_packages_file(old_filename, opt_f)
        for k in list(old_packages.packages.keys()):
            pkg = old_packages.packages[k]
            old_pkg_hash[pkg.filename] = pkg
        try:
            with open(stamplist_filename, "r") as stamplist_filename_hdl:
                for line in stamplist_filename_hdl:
                    line = line.strip()
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        stamp, filename = parts
                        pkgs_stamps[filename] = int(stamp)
        except (IOError, ValueError):
            pass

    if verbose:
        sys.stderr.write("Reading in all the package info from %s\n" % (pkg_dir, ))

    files = []
    opkg_extensions = ['.ipk', '.opk', '.deb']
    for dirpath, _, filenames in os.walk(pkg_dir):
        for filename in filenames:
            ext = os.path.splitext(filename)[1]
            if ext in opkg_extensions:
                files.append(os.path.join(dirpath, filename))

    files.sort()
    for abspath in files:
        try:
            filename = os.path.relpath(abspath, pkg_dir)
            pkg = None
            stat = os.stat(abspath)
            if filename in old_pkg_hash:
                if filename in pkgs_stamps and int(stat.st_ctime) == pkgs_stamps[filename]:
                    if verbose:
                        sys.stderr.write("Found %s in Packages\n" % (filename,))
                    pkg = old_pkg_hash[filename]
                else:
                    sys.stderr.write("Found %s in Packages, but ctime differs - re-reading\n"
                                     % (filename,))

            if not pkg:
                if verbose:
                    sys.stderr.write("Reading info for package %s\n" % (filename,))
                pkg = Package(abspath, relpath=pkg_dir, all_fields=opt_f)

            if opt_a:
                pkg_key = ("%s:%s:%s" % (pkg.package, pkg.architecture, pkg.version))
            else:
                pkg_key = ("%s:%s" % (pkg.package, pkg.architecture))

            if pkg_key in packages.packages:
                prev_filename = packages.packages[pkg_key].filename
            else:
                prev_filename = ""
            ret = packages.add_package(pkg, opt_a)
            pkgs_stamps[filename] = stat.st_ctime
            if ret == 0:
                if prev_filename:
                    # old package was displaced by newer
                    if opt_m:
                        to_morgue(prev_filename, pkg_dir, verbose)
                    if opt_s:
                        print(("%s/%s" % (pkg_dir, prev_filename)))
            else:
                if opt_m:
                    to_morgue(filename, pkg_dir, verbose)
                if opt_s:
                    print(filename)
        except (OSError, IOError) as ex:
            sys.stderr.write("Package or directory error: %s\n" % (ex,))
            continue

    try:
        with open(stamplist_filename, "w") as pkgs_stamps_file:
            for filename in list(pkgs_stamps.keys()):
                pkgs_stamps_file.write("%d %s\n" % (pkgs_stamps[filename], filename))
    except (IOError, OSError):
        pass

    if opt_s:
        return True

    if verbose:
        sys.stderr.write("Generating Packages file\n")
    if packages_filename:
        tmp_packages_filename = ("%s.%d" % (packages_filename, os.getpid()))
        pkgs_file = open(tmp_packages_filename, "w")
    names = list(packages.packages.keys())
    names.sort()
    for name in names:
        try:
            pkg = packages.packages[name]
            if locales_dir and pkg.depends:
                depends = pkg.depends.split(',')
                locale = None
                for depend in depends:
                    match = re.match('.*virtual-locale-([a-zA-Z]+).*', depend)
                    match_by_pkg = re.match('locale-base-([a-zA-Z]+)([-+])?.*', pkg.package)
                    if match:
                        locale = match.group(1)
                    if match_by_pkg:
                        locale = match_by_pkg.group(1)
                if locale:
                    to_locale(pkg.filename, locale, pkg_dir, locales_dir, verbose)
                    continue
            if verbose:
                sys.stderr.write("Writing info for package %s\n" % (pkg.package,))
            if packages_filename:
                pkgs_file.write(pkg.print(checksum))
            else:
                print(pkg.print(checksum))
        except (OSError, IOError) as ex:
            sys.stderr.write("Package write error: %s\n" % (ex,))
            continue

    if packages_filename:
        pkgs_file.close()
        gzip_filename = ("%s.gz" % packages_filename)
        tmp_gzip_filename = ("%s.%d" % (gzip_filename, os.getpid()))
        gzip_cmd = "gzip -9c < %s > %s" % (tmp_packages_filename, tmp_gzip_filename)
        subprocess.call(gzip_cmd, shell=True)
        os.rename(tmp_packages_filename, packages_filename)
        os.rename(tmp_gzip_filename, gzip_filename)

    if filelist_filename:
        if verbose:
            sys.stderr.write("Generate Packages.filelist file\n")
        files_data = {}
        names = list(packages.packages.keys())
        names.sort()
        for name in names:
            try:
                if verbose:
                    sys.stderr.write("Reading filelist for package '%s'\n" % name)
                file_list = packages[name].get_file_list_dir(pkg_dir)
            except (OSError, IOError):
                continue
            for filepath in file_list:
                (_, filename) = os.path.split(filepath)
                if not filename:
                    continue
                if filename not in files_data:
                    files_data[filename] = name + ':' + filepath
                else:
                    files_data[filename] = files_data[filename] + ',' + name + ':' + filepath

        tmp_filelist_filename = ("%s.%d" % (filelist_filename, os.getpid()))
        with open(tmp_filelist_filename, "w") as tmp_filelist_filename_hdl:
            names = list(files_data.keys())
            names.sort()
            for name in names:
                tmp_filelist_filename_hdl.write("%s %s\n" % (name, files_data[name]))
        if posixpath.exists(filelist_filename):
            os.unlink(filelist_filename)
        os.rename(tmp_filelist_filename, filelist_filename)
    return True

def main():
    """ Script entry point """
    parser = argparse.ArgumentParser(description='Opkg index creation tool')
    parser.add_argument('-s', dest='opt_s', default=0, action="store_true", help='Old simulation mode')
    parser.add_argument('-m', dest='opt_m', action="store_true", help='Archive old packages')
    parser.add_argument('-a', dest='opt_a', action='store_true', help='Add version information')
    parser.add_argument('-f', dest='opt_f', action='store_true', help='Include user-defined fields')
    parser.add_argument('-l', dest='filelist_filename', default=None, help='Packages filelist name')
    parser.add_argument('-p', dest='packages_filename', default=None, help='Package index filename')
    parser.add_argument('-r', dest='old_filename', help='Old Package index filename')
    parser.add_argument('-L', dest='locales_dir', help='Locales dirname')
    parser.add_argument('-v', dest='verbose', action="store_true", default=0, help='Verbose output')
    parser.add_argument('--checksum', action='append', dest='checksum', choices=['md5', 'sha256'], help='Select checksum type (default is md5)')
    parser.add_argument('packagesdir', help='Directory to be indexed')
    args = parser.parse_args()

    checksum = args.checksum if args.checksum else ['md5']

    make_index(pkg_dir=args.packagesdir, packages_filename=args.packages_filename, 
               filelist_filename=args.filelist_filename, old_filename=args.old_filename, 
               locales_dir=args.locales_dir, verbose=args.verbose, opt_m=args.opt_m, 
               opt_a=args.opt_a, opt_f=args.opt_f, opt_s=args.opt_s, checksum=checksum)

if __name__ == "__main__":
    main()
