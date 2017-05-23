#    This file is part of cfelpyutils.
#
#    cfelpyutils is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    cfelpyutils is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with cfelpyutils.  If not, see <http://www.gnu.org/licenses/>.
"""
Utilities for interoperability with the CrystFEL software package.

This module contains reimplementation of Crystfel functions and utilities.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from builtins import str

from collections import namedtuple
import h5py
import numpy


class _Stack:
    def __init__(self, path, data):

        self._data_type = type(data)

        if isinstance(data, (str, int, float)):
            self._data_shape = (1,)
        else:
            self._data_shape = data.shape

        self._data_to_write = data
        self._path = path

    def write_initial_slice(self, file_handle, max_num_slices):

        file_handle.create_dataset(self._path, shape=(max_num_slices,) + self._data_shape,
                                   maxshape=(max_num_slices,) + self._data_shape,
                                   chunks=(1,) + self._data_shape)
        file_handle[self._path][0] = self._data_to_write

        self._data_to_write = None

    def write_slice(self, file_handle, curr_slice):

        file_handle[self._path][curr_slice] = self._data_to_write

        self._data_to_write = None

    def append_data(self, data):

        if self._data_to_write is not None:
            raise RuntimeError('Cannot append data to the stack entry at {}. The previous slice has not been written '
                               'yet.'.format(self._path))

        if type(data) != self._data_type:
            raise RuntimeError('The type of the input data does not match what is already present in the stack.')

        if isinstance(data, (str, int, float)):
            curr_data_shape = (1,)
        else:
            curr_data_shape = data.shape

        if curr_data_shape != self._data_shape:
            raise RuntimeError('The shape of the input data does not match what is already present in the stack.')

        self._data_to_write = data

    def finalize(self, file_handle, curr_slice):

        if self._data_to_write is not None:
            raise RuntimeError('Cannot finalize the stack at {}, there is data waiting to be '
                               'written.'.format(self._path))

        final_size = curr_slice

        file_handle[self._path].resize((final_size,) + self._data_shape)


def _validate_data(data):
    if not isinstance(data, (str, int, float, numpy.ndarray)):
        raise RuntimeError('The CXI Writer only accepts numpy objects, numbers and strings.')


class CXIWriter:
    def __init__(self, filename, max_num_slices=5000):

        self._cxi_stacks = {}
        self._pending_simple_entries = []
        self._intialized = False
        self._curr_slice = 0
        self._max_num_slices = max_num_slices
        self._file_is_open = False
        self._initialized = False

        try:
            self._fh = h5py.File(filename, 'w')
            self._file_is_open = True

        except OSError:
            raise RuntimeError('Error opening the cxi file: ', filename)

    def _write_simple_entry(self, entry):

        if entry.path in self._fh:
            if entry.overwrite is True:
                del self._fh[entry.path]
            else:
                raise RuntimeError('Cannot write the entry. Data is already present at the specified path.')

        self._fh.create_dataset(entry.path, data=entry.data)

    def add_stack_to_writer(self, name, path, initial_data, overwrite=True):

        _validate_data(initial_data)

        if self._initialized is True:
            raise RuntimeError('Adding stacks to the writer is not possible after initialization.')

        if name in self._cxi_stacks:
            if overwrite is True:
                del (self._cxi_stacks[name])
            else:
                raise RuntimeError('Cannot write the entry. Data is already present at the specified path.')

        new_stack = _Stack(path, initial_data)
        self._cxi_stacks[name] = new_stack

    def write_entry(self, path, data, overwrite=False):

        _validate_data(data)

        SimpleEntry = namedtuple('SimpleEntry', ['path', 'data', 'overwrite'])
        new_entry = SimpleEntry(path, data, overwrite)

        if self._initialized is not True:
            self._pending_simple_entries.append(new_entry)
        else:
            self._write_simple_entry(new_entry)

    def initialize_stacks(self):

        if self._file_is_open is not True:
            raise RuntimeError('The file is closed. Cannot initialize the file.')

        if self._initialized is True:
            raise RuntimeError('The file is already initialized. Cannot initialize file.')

        for entry in self._cxi_stacks.values():
            entry.write_initial_slice(self._fh, self._max_num_slices)

        self._curr_slice += 1

        for entry in self._pending_simple_entries:
            self._write_simple_entry(entry)
        self._pending_simple_entries = []

        self._initialized = True

    def append_to_stack(self, name, data):

        _validate_data(data)

        if self._initialized is False:
            raise RuntimeError('Cannot append to a stack before initialization of the file.')

        if name not in self._cxi_stacks:
            raise RuntimeError('Cannot append to stack {}. The stack does not exists.'.format(name))

        try:
            self._cxi_stacks[name].append_data(data)
        except RuntimeError as e:
            raise RuntimeError('Error appending to stack {}: {}'.format(name, e))

    def write_stack_slice_and_increment(self):

        if self._file_is_open is not True:
            raise RuntimeError('The file is closed. The slice cannot be written.')

        if self._initialized is False:
            raise RuntimeError('Cannot write slice. The file is not initialized.')

        if self._curr_slice >= self._max_num_slices:
            raise RuntimeError('The file already holds the maximum allowed number of slices, and should be closed')

        for entry in self._cxi_stacks.values():
            if entry._data_to_write is None:
                raise RuntimeError('The slice is incomplete and will not be written. The following stac is not '
                                   'present in the current slice:', entry.path)

        for entry in self._cxi_stacks.values():
            entry.write_slice(self._fh, self._curr_slice)

        self._curr_slice += 1

    def get_file_handle(self):

        if self._file_is_open is not True:
            raise RuntimeError('The file is closed. Cannot get the file handle.')

        return self._fh

    def close_file(self):

        if self._file_is_open is not True:
            raise RuntimeError('The file is already closed. Cannot close the file.')

        for entry in self._cxi_stacks.values():
            entry.finalize(self._fh, self._curr_slice)

        self._fh.close()

        self._file_is_open = False


if __name__ == "__main__":

    c1 = 0
    c2 = 0

    f1 = CXIWriter('/data/test1.h5', )
    f2 = CXIWriter('/data/test2.h5', )

    f1.add_stack_to_writer('detector1', '/entry_1/detector_1/data', numpy.random.rand(2, 2))
    f2.add_stack_to_writer('detector2', '/entry_1/detector_1/data', numpy.random.rand(3, 2))

    f1.add_stack_to_writer('counter1', '/entry_1/detector_1/count', c1)
    f2.add_stack_to_writer('counter2', '/entry_1/detector_1/count', c2)

    f1.write_entry('/entry_1/detector_1/name', 'FrontCSPAD')
    f2.write_entry('/entry_1/detector_1/name', 'BackCSPAD')

    f1.initialize_stacks()
    f2.initialize_stacks()

    for i in range(1, 60):
        print('Writing slice:', i)
        a = numpy.random.rand(2, 2)
        b = numpy.random.rand(2, 2)

        c1 += 1
        c2 += 2

        f1.append_to_stack('detector1', a)
        f2.append_to_stack('detector2', b)

        f1.append_to_stack('counter1', c1)
        f2.append_to_stack('counter2', c2)

        f1.write_stack_slice_and_increment()
        f2.write_stack_slice_and_increment()

    f1.close_file()
    f2.close_file()