# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from codecs import open
import json
import locale
from os import environ, stat
from os.path import join

import pytest

from libarchive import memory_reader, memory_writer, file_reader, ffi
from libarchive.write import new_archive_entry_from_path

from . import (data_dir, get_entries, get_tarinfos, generate_contents,
               create_sparse_file)


locale.setlocale(locale.LC_ALL, '')

# needed for sane time stamp comparison
environ['TZ'] = 'UTC'


def test_entry_properties():

    buf = bytes(bytearray(1000000))
    with memory_writer(buf, 'gnutar') as archive:
        archive.add_files('README.rst')

    with memory_reader(buf) as archive:
        for entry in archive:
            assert entry.mode == stat('README.rst')[0]
            assert not entry.isblk
            assert not entry.ischr
            assert not entry.isdir
            assert not entry.isfifo
            assert not entry.islnk
            assert not entry.issym
            assert not entry.linkpath
            assert entry.linkpath == entry.linkname
            assert entry.isreg
            assert entry.isfile
            assert not entry.issock
            assert not entry.isdev
            assert b'rw' in entry.strmode
            assert entry.pathname == entry.path
            assert entry.pathname == entry.name


@pytest.mark.parametrize('tar_file', ['testtar.tar', ])
def test_entry_name_decoding(tar_file):
    """ Test that the entry names are decoded to utf8 correctly """
    path = join(data_dir, tar_file)

    with file_reader(path) as arch:
        for entry in arch:
            # Use str find method to test it was converted from bytes to a
            # str/unicode
            entry.name.find('not there')


# - 8k file, hole from 0->4096
@pytest.mark.parametrize('size, write_map, sparse_map',
                         [(8192, [(4096, 4096), ], [(4096, 4096), ]),
                          (4096, [(0, 4096), ], []),
                          (8192, [(0, 4096), ], [(0, 4096), (8192, 0)])
                          ])
def test_entry_sparse(tmpdir, size, write_map, sparse_map):
    """ Test that we can write & read back a sparse file and the sparse map """
    fname = tmpdir.join('sparse1').strpath

    create_sparse_file(fname, write_map, size)

    buf = bytes(bytearray(1000000))
    with memory_writer(buf, 'pax') as archive:
        archive.add_files(fname)

    with memory_reader(buf) as archive:
        for entry in archive:
            assert entry.name == fname.lstrip('/')
            assert entry.mode == stat(fname)[0]
            assert entry.size == size

            assert len(entry.sparse_map) == len(sparse_map)
            assert entry.sparse_map == sparse_map


@pytest.mark.parametrize('name', ['testtar.tar', ])
def test_sparse_formats(name):
    """ test for a good sparse map from all of the various sparse formats """
    path = join(data_dir, name)
    expected_map = [(4096, 4096), (12288, 4096), (20480, 4096), (28672, 4096),
                    (36864, 4096), (45056, 4096), (53248, 4096),
                    (61440, 4096), (69632, 4096), (77824, 4096), (86016, 0)]

    with file_reader(path) as arch:
        for entry in arch:
            try:
                if entry.name.startswith('gnu/sparse'):
                    assert entry.size == 86016
                    assert entry.sparse_map == expected_map
            except UnicodeDecodeError:
                # py27 fails on some unicode
                pass


@pytest.mark.parametrize('sparse_map',
                         [[(0, 4096), (8192, 0)],
                          [(0, 0), (4096, 4096)]
                          ])
def test_entry_sparse_manual(tmpdir, sparse_map):
    """ Can we archive a partial non-sparse file as sparse """
    fname = tmpdir.join('sparse1').strpath

    size = 8192
    with open(fname, 'w') as testf:
        testf.write(generate_contents(8192))

    buf = bytes(bytearray(1000000))
    with memory_writer(buf, 'pax') as archive:
        with new_archive_entry_from_path(fname) as entry:
            assert len(entry.sparse_map) == 0
            entry.sparse_map.extend(sparse_map)

            # not using archive.add_entries, that assumes the entry comes from
            # another archive and tries to use entry.get_blocks()
            write_p = archive._pointer

            ffi.write_header(write_p, entry.entry_p)

            with open(fname, 'rb') as testf:
                entry_data = testf.read()
                ffi.write_data(write_p, entry_data, len(entry_data))
            ffi.write_finish_entry(write_p)

    with memory_reader(buf) as archive:
        for entry in archive:
            assert entry.name == fname.lstrip('/')
            assert entry.mode == stat(fname)[0]
            assert entry.size == size

            assert len(entry.sparse_map) == len(sparse_map)
            assert entry.sparse_map == sparse_map


def test_check_ArchiveEntry_against_TarInfo():
    for name in ('special.tar', 'tar_relative.tar'):
        path = join(data_dir, name)
        tarinfos = list(get_tarinfos(path))
        entries = list(get_entries(path))
        for tarinfo, entry in zip(tarinfos, entries):
            assert tarinfo == entry
        assert len(tarinfos) == len(entries)


def test_check_archiveentry_using_python_testtar():
    check_entries(join(data_dir, 'testtar.tar'))


def test_check_archiveentry_with_unicode_and_binary_entries_tar():
    check_entries(join(data_dir, 'unicode.tar'))


def test_check_archiveentry_with_unicode_and_binary_entries_zip():
    check_entries(join(data_dir, 'unicode.zip'))


def test_check_archiveentry_with_unicode_and_binary_entries_zip2():
    check_entries(join(data_dir, 'unicode2.zip'), ignore='mode')


def test_check_archiveentry_with_unicode_entries_and_name_zip():
    check_entries(join(data_dir, '\ud504\ub85c\uadf8\ub7a8.zip'))


def check_entries(test_file, regen=False, ignore=''):
    ignore = ignore.split()
    fixture_file = test_file + '.json'
    if regen:
        entries = list(get_entries(test_file))
        with open(fixture_file, 'w', encoding='UTF-8') as ex:
            json.dump(entries, ex, indent=2)
    with open(fixture_file, encoding='UTF-8') as ex:
        expected = json.load(ex)
    actual = list(get_entries(test_file))
    for e1, e2 in zip(actual, expected):
        for key in ignore:
            e1.pop(key)
            e2.pop(key)
        assert e1 == e2
