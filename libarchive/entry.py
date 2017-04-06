from __future__ import division, print_function, unicode_literals

from contextlib import contextmanager
from ctypes import cast, c_byte, c_char_p, c_void_p, c_long, c_longlong, pointer, byref, create_string_buffer

from . import ffi


@contextmanager
def new_archive_entry():
    entry_p = ffi.entry_new()
    try:
        yield entry_p
    finally:
        ffi.entry_free(entry_p)


def format_time(seconds, nanos):
    """ return float of seconds.nanos when nanos set, or seconds when not """
    if nanos:
        return float(seconds) + float(nanos) / 1000000000.0
    return int(seconds)


def entry_sparse_map(entry_p):
    """ return the next sparse entry as (offset, length) """
    offset = c_longlong()
    length = c_longlong()

    off_p = byref(offset)
    len_p = byref(length)

    # loop until we see ARCHIVE_WARN
    while True:
        if ffi.entry_sparse_next(entry_p, off_p, len_p) != ffi.ARCHIVE_OK:
            raise StopIteration()

        yield(offset.value, length.value)


class SparseMap(list):
    """ Sparse map handling for archive entries

        The map is a ordered list of (offset, length) of data blocks
    """

    def __init__(self, archive_entry):
        """ setup internal data """
        super(SparseMap, self).__init__()
        self._arch_e = archive_entry
        self._update_from_entry()

    def __setitem__(self, index, value):
        """ Not supported: no replacing of existing data """
        raise NotImplementedError()

    def insert(self, index, value):
        """ Not supported, inserting should be done with append or extend """
        raise NotImplementedError()

    def _add_map(self, offset, length):
        """ Add a new sparse map entry """
        ffi.entry_sparse_add_entry(self._arch_e.entry_p, offset, length)
        super(SparseMap, self).append((offset, length))

    def append(self, map_entry):
        """ add new map entry """
        (offset, length) = map_entry
        self._add_map(offset, length)

    def extend(self, iterable):
        """ add all the map entries in iterable """
        for (offset, length) in iterable:
            self._add_map(offset, length)

    def _update_from_entry(self):
        """ populate a map from the archive entry """
        entry_p = self._arch_e.entry_p

        # make sure we start at the beginning
        ffi.entry_sparse_reset(entry_p)

        self.extend(entry_sparse_map(entry_p))


class ArchiveEntry(object):

    def __init__(self, archive_p, entry_p):
        self._archive_p = archive_p
        self._entry_p = entry_p
        self._sparse_map = None

    def __str__(self):
        return self.pathname

    @property
    def entry_p(self):
        """ return entry pointer to be used by archive entry API functions """
        return self._entry_p

    @property
    def filetype(self):
        return ffi.entry_filetype(self._entry_p)

    @property
    def uid(self):
        return ffi.entry_uid(self._entry_p)

    @property
    def gid(self):
        return ffi.entry_gid(self._entry_p)

    def get_blocks(self, block_size=ffi.page_size):
        archive_p = self._archive_p
        buf = create_string_buffer(block_size)
        read = ffi.read_data
        while 1:
            r = read(archive_p, buf, block_size)
            if r == 0:
                break
            yield buf.raw[0:r]

    @property
    def isblk(self):
        return self.filetype & 0o170000 == 0o060000

    @property
    def ischr(self):
        return self.filetype & 0o170000 == 0o020000

    @property
    def isdir(self):
        return self.filetype & 0o170000 == 0o040000

    @property
    def isfifo(self):
        return self.filetype & 0o170000 == 0o010000

    @property
    def islnk(self):
        return bool(ffi.entry_hardlink_w(self._entry_p) or
                    ffi.entry_hardlink(self._entry_p))

    @property
    def issym(self):
        return self.filetype & 0o170000 == 0o120000

    def _linkpath(self):
        return (ffi.entry_symlink_w(self._entry_p) or
                ffi.entry_hardlink_w(self._entry_p) or
                ffi.entry_symlink(self._entry_p) or
                ffi.entry_hardlink(self._entry_p))

    # aliases to get the same api as tarfile
    linkpath = property(_linkpath)
    linkname = property(_linkpath)

    @property
    def isreg(self):
        return self.filetype & 0o170000 == 0o100000

    @property
    def isfile(self):
        return self.isreg

    @property
    def issock(self):
        return self.filetype & 0o170000 == 0o140000

    @property
    def isdev(self):
        return self.ischr or self.isblk or self.isfifo or self.issock

    @property
    def atime(self):
        sec_val = ffi.entry_atime(self._entry_p)
        nsec_val = ffi.entry_atime_nsec(self._entry_p)
        return format_time(sec_val, nsec_val)

    def set_atime(self, timestamp_sec, timestamp_nsec):
        return ffi.entry_set_atime(self._entry_p,
                                   timestamp_sec, timestamp_nsec)

    @property
    def mtime(self):
        sec_val = ffi.entry_mtime(self._entry_p)
        nsec_val = ffi.entry_mtime_nsec(self._entry_p)
        return format_time(sec_val, nsec_val)

    def set_mtime(self, timestamp_sec, timestamp_nsec):
        return ffi.entry_set_mtime(self._entry_p,
                                   timestamp_sec, timestamp_nsec)

    @property
    def ctime(self):
        sec_val = ffi.entry_ctime(self._entry_p)
        nsec_val = ffi.entry_ctime_nsec(self._entry_p)
        return format_time(sec_val, nsec_val)

    def set_ctime(self, timestamp_sec, timestamp_nsec):
        return ffi.entry_set_ctime(self._entry_p,
                                   timestamp_sec, timestamp_nsec)

    def _getpathname(self):
        name = (ffi.entry_pathname_w(self._entry_p) or
                ffi.entry_pathname(self._entry_p))
        if isinstance(name, bytes):
            return name.decode('utf8', 'surrogateescape')
        else:
            return name

    def _setpathname(self, value):
        if not isinstance(value, bytes):
            value = value.encode('utf8')
        ffi.entry_update_pathname_utf8(self._entry_p, c_char_p(value))

    pathname = property(_getpathname, _setpathname)
    # aliases to get the same api as tarfile
    path = property(_getpathname, _setpathname)
    name = property(_getpathname, _setpathname)

    @property
    def size(self):
        if ffi.entry_size_is_set(self._entry_p):
            return ffi.entry_size(self._entry_p)

    @property
    def mode(self):
        return ffi.entry_mode(self._entry_p)

    @property
    def strmode(self):
        # note we strip the mode because archive_entry_strmode
        # returns a trailing space: strcpy(bp, "?rwxrwxrwx ");
        return ffi.entry_strmode(self._entry_p).strip()

    @property
    def rdevmajor(self):
        return ffi.entry_rdevmajor(self._entry_p)

    @property
    def rdevminor(self):
        return ffi.entry_rdevminor(self._entry_p)

    @property
    def sparse_map(self):
        if self._sparse_map is None:
            self._sparse_map = SparseMap(self)
        return self._sparse_map

    def pax_headers(self):
        # TODO:
        # setup cache so we only need to create the dict once
        headers = {}
        # reset back to beginning to walk
        numh = ffi.entry_pax_kw_reset(self._entry_p)
        print("num headers:", numh)

        key = c_char_p()
        value = c_void_p()
        value_len = c_longlong()

        # loop until we see ARCHIVE_WARN
        while True:
            if ffi.entry_pax_kw_next(self._entry_p, key, value, byref(value_len)) != ffi.ARCHIVE_OK:
                break

            # per PAX standard, keys are in utf-8
            # XXX: libarchive uses url decode/encode, not utf-8 alone
            key_str = key.value.decode('utf-8')
            print("key: {0}".format(key_str))

            # start with bytes, might translate to other formats...
            print("value_len:", value_len.value)
            val_bytes = bytearray((c_byte * value_len.value).from_address(value.value))
            print("val_bytes:", val_bytes)
            #val_bytes = bytearray(cast(value, c_char_p).value[:value_len.value])
            try:
                val_str = val_bytes.decode('utf-8', 'surrogateescape')
            except UnicodeDecodeError:
                print("binary data in {0}".format(key_str))
                val_str = val_bytes
            print("val_str:", val_str)

            # use set default, as we are walking the attributes in reverse order and only need to
            # see the last one set -- it overrides earlier ones.
            headers.setdefault(key_str, val_str)

        print("headers:", headers)
        return headers
