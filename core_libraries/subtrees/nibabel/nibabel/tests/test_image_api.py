"""Validate image API

What is the image API?

* ``img.dataobj``

    * Returns ``np.ndarray`` from ``np.array(img.databj)``
    * Has attribute ``shape``

* ``img.header`` (image metadata) (changes in the image metadata should not
  change any of ``dataobj``, ``affine``, ``shape``)
* ``img.affine`` (4x4 float ``np.ndarray`` relating spatial voxel coordinates
  to world space)
* ``img.shape`` (shape of data as read with ``np.array(img.dataobj)``
* ``img.get_fdata()`` (returns floating point data as read with
  ``np.array(img.dataobj)`` and the cast to float);
* ``img.uncache()`` (``img.get_fdata()`` (recommended) and ``img.get_data()``
  (deprecated) are allowed to cache the result of the array creation.  If they
  do, this call empties that cache.  Implement this as a no-op if
  ``get_fdata()``, ``get_data()`` do not cache.)
* ``img[something]`` generates an informative TypeError
* ``img.in_memory`` is True for an array image, and for a proxy image that is
  cached, but False otherwise.
"""

import io
import pathlib
import warnings
from functools import partial
from itertools import product

import numpy as np

from ..optpkg import optional_package

_, have_scipy, _ = optional_package('scipy')
_, have_h5py, _ = optional_package('h5py')

import unittest

import pytest
from numpy.testing import assert_allclose, assert_almost_equal, assert_array_equal, assert_warns

from nibabel.arraywriters import WriterError
from nibabel.testing import (
    assert_data_similar,
    bytesio_filemap,
    bytesio_round_trip,
    clear_and_catch_warnings,
    expires,
    nullcontext,
)

from .. import (
    AnalyzeImage,
    GiftiImage,
    MGHImage,
    Minc1Image,
    Minc2Image,
    Nifti1Image,
    Nifti1Pair,
    Nifti2Image,
    Nifti2Pair,
    Spm2AnalyzeImage,
    Spm99AnalyzeImage,
    brikhead,
    is_proxy,
    minc1,
    minc2,
    parrec,
)
from ..deprecator import ExpiredDeprecationError
from ..spatialimages import SpatialImage
from ..tmpdirs import InTemporaryDirectory
from .test_api_validators import ValidateAPI
from .test_brikhead import EXAMPLE_IMAGES as AFNI_EXAMPLE_IMAGES
from .test_minc1 import EXAMPLE_IMAGES as MINC1_EXAMPLE_IMAGES
from .test_minc2 import EXAMPLE_IMAGES as MINC2_EXAMPLE_IMAGES
from .test_parrec import EXAMPLE_IMAGES as PARREC_EXAMPLE_IMAGES


def maybe_deprecated(meth_name):
    return pytest.deprecated_call() if meth_name == 'get_data' else nullcontext()


class GenericImageAPI(ValidateAPI):
    """General image validation API"""

    # Whether this image type can do scaling of data
    has_scaling = False
    # Whether the image can be saved to disk / file objects
    can_save = False
    # Filename extension to which to save image; only used if `can_save` is
    # True
    standard_extension = '.img'

    def obj_params(self):
        """Return generator returning (`img_creator`, `img_params`) tuples

        ``img_creator`` is a function taking no arguments and returning a fresh
        image.  We need to return this ``img_creator`` function rather than an
        image instance so we can recreate the images fresh for each of multiple
        tests run from the ``validate_xxx`` autogenerated test methods.  This
        allows the tests to modify the image without having an effect on the
        later tests in the same function, because each test will create a fresh
        image with ``img_creator``.

        Returns
        -------
        func_params_gen : generator
            Generator returning tuples with:

            * img_creator : callable
              Callable returning a fresh image for testing
            * img_params : mapping
              Expected properties of image returned from ``img_creator``
              callable.  Key, value pairs should include:

              * ``data`` : array returned from ``get_fdata()`` on image - OR -
                ``data_summary`` : dict with data ``min``, ``max``, ``mean``;
              * ``shape`` : shape of image;
              * ``affine`` : shape (4, 4) affine array for image;
              * ``dtype`` : dtype of data returned from ``np.asarray(dataobj)``;
              * ``is_proxy`` : bool, True if image data is proxied;

        Notes
        -----
        Passing ``data_summary`` instead of ``data`` allows you gentle user to
        avoid having to have a saved copy of the entire data array from example
        images for testing.
        """
        raise NotImplementedError

    def validate_header(self, imaker, params):
        # Check header API
        img = imaker()
        hdr = img.header  # we can fetch it
        # Read only
        with pytest.raises(AttributeError):
            img.header = hdr

    def validate_filenames(self, imaker, params):
        # Validate the filename, file_map interface

        if not self.can_save:
            raise unittest.SkipTest
        img = imaker()
        img.set_data_dtype(np.float32)  # to avoid rounding in load / save
        # Make sure the object does not have a file_map
        img.file_map = None
        # The bytesio_round_trip helper tests bytesio load / save via file_map
        rt_img = bytesio_round_trip(img)
        assert_array_equal(img.shape, rt_img.shape)
        assert_almost_equal(img.get_fdata(), rt_img.get_fdata())
        assert_almost_equal(np.asanyarray(img.dataobj), np.asanyarray(rt_img.dataobj))
        # Give the image a file map
        klass = type(img)
        rt_img.file_map = bytesio_filemap(klass)
        # This object can now be saved and loaded from its own file_map
        rt_img.to_file_map()
        rt_rt_img = klass.from_file_map(rt_img.file_map)
        assert_almost_equal(img.get_fdata(), rt_rt_img.get_fdata())
        assert_almost_equal(np.asanyarray(img.dataobj), np.asanyarray(rt_img.dataobj))
        # get_ / set_ filename
        fname = 'an_image' + self.standard_extension
        for path in (fname, pathlib.Path(fname)):
            img.set_filename(path)
            assert img.get_filename() == str(path)
            assert img.file_map['image'].filename == str(path)
        # to_ / from_ filename
        fname = 'another_image' + self.standard_extension
        for path in (fname, pathlib.Path(fname)):
            with InTemporaryDirectory():
                # Validate that saving or loading a file doesn't use deprecated methods internally
                with clear_and_catch_warnings() as w:
                    warnings.filterwarnings(
                        'error', category=DeprecationWarning, module=r'nibabel.*'
                    )
                    img.to_filename(path)
                    rt_img = img.__class__.from_filename(path)
                assert_array_equal(img.shape, rt_img.shape)
                assert_almost_equal(img.get_fdata(), rt_img.get_fdata())
                assert_almost_equal(np.asanyarray(img.dataobj), np.asanyarray(rt_img.dataobj))
                del rt_img  # to allow windows to delete the directory

    def validate_no_slicing(self, imaker, params):
        img = imaker()
        with pytest.raises(TypeError):
            img['string']
        with pytest.raises(TypeError):
            img[:]

    @expires('5.0.0')
    def validate_get_data_deprecated(self, imaker, params):
        img = imaker()
        with pytest.deprecated_call():
            data = img.get_data()
        assert_array_equal(np.asanyarray(img.dataobj), data)


class GetSetDtypeMixin:
    """Adds dtype tests

    Add this one if your image has ``get_data_dtype`` and ``set_data_dtype``.
    """

    def validate_dtype(self, imaker, params):
        # data / storage dtype
        img = imaker()
        # Need to rename this one
        assert img.get_data_dtype().type == params['dtype']
        # dtype survives round trip
        if self.has_scaling and self.can_save:
            with np.errstate(invalid='ignore'):
                rt_img = bytesio_round_trip(img)
            assert rt_img.get_data_dtype().type == params['dtype']
        # Setting to a different dtype
        img.set_data_dtype(np.float32)  # assumed supported for all formats
        assert img.get_data_dtype().type == np.float32
        # dtype survives round trip
        if self.can_save:
            rt_img = bytesio_round_trip(img)
            assert rt_img.get_data_dtype().type == np.float32


class DataInterfaceMixin(GetSetDtypeMixin):
    """Test dataobj interface for images with array backing

    Use this mixin if your image has a ``dataobj`` property that contains an
    array or an array-like thing.
    """

    meth_names = ('get_fdata',)

    def validate_data_interface(self, imaker, params):
        # Check get data returns array, and caches
        img = imaker()
        assert img.shape == img.dataobj.shape
        assert img.ndim == len(img.shape)
        assert_data_similar(img.dataobj, params)
        for meth_name in self.meth_names:
            if params['is_proxy']:
                self._check_proxy_interface(imaker, meth_name)
            else:  # Array image
                self._check_array_interface(imaker, meth_name)
            method = getattr(img, meth_name)
            # Data shape is same as image shape
            with maybe_deprecated(meth_name):
                assert img.shape == method().shape
            # Data ndim is same as image ndim
            with maybe_deprecated(meth_name):
                assert img.ndim == method().ndim
            # Values to get_data caching parameter must be 'fill' or
            # 'unchanged'
            with maybe_deprecated(meth_name), pytest.raises(ValueError):
                method(caching='something')
        # dataobj is read only
        fake_data = np.zeros(img.shape, dtype=img.get_data_dtype())
        with pytest.raises(AttributeError):
            img.dataobj = fake_data
        # So is in_memory
        with pytest.raises(AttributeError):
            img.in_memory = False

    def _check_proxy_interface(self, imaker, meth_name):
        # Parameters assert this is an array proxy
        img = imaker()
        # Does is_proxy agree?
        assert is_proxy(img.dataobj)
        # Confirm it is not a numpy array
        assert not isinstance(img.dataobj, np.ndarray)
        # Confirm it can be converted to a numpy array with asarray
        proxy_data = np.asarray(img.dataobj)
        proxy_copy = proxy_data.copy()
        # Not yet cached, proxy image: in_memory is False
        assert not img.in_memory
        # Load with caching='unchanged'
        method = getattr(img, meth_name)
        with maybe_deprecated(meth_name):
            data = method(caching='unchanged')
        # Still not cached
        assert not img.in_memory
        # Default load, does caching
        with maybe_deprecated(meth_name):
            data = method()
        # Data now cached. in_memory is True if either of the get_data
        # or get_fdata caches are not-None
        assert img.in_memory
        # We previously got proxy_data from disk, but data, which we
        # have just fetched, is a fresh copy.
        assert not proxy_data is data
        # asarray on dataobj, applied above, returns same numerical
        # values.  This might not be true get_fdata operating on huge
        # integers, but lets assume that's not true here.
        assert_array_equal(proxy_data, data)
        # Now caching='unchanged' does nothing, returns cached version
        with maybe_deprecated(meth_name):
            data_again = method(caching='unchanged')
        assert data is data_again
        # caching='fill' does nothing because the cache is already full
        with maybe_deprecated(meth_name):
            data_yet_again = method(caching='fill')
        assert data is data_yet_again
        # changing array data does not change proxy data, or reloaded
        # data
        data[:] = 42
        assert_array_equal(proxy_data, proxy_copy)
        assert_array_equal(np.asarray(img.dataobj), proxy_copy)
        # It does change the result of get_data
        with maybe_deprecated(meth_name):
            assert_array_equal(method(), 42)
        # until we uncache
        img.uncache()
        # Which unsets in_memory
        assert not img.in_memory
        with maybe_deprecated(meth_name):
            assert_array_equal(method(), proxy_copy)
        # Check caching='fill' does cache data
        img = imaker()
        method = getattr(img, meth_name)
        assert not img.in_memory
        with maybe_deprecated(meth_name):
            data = method(caching='fill')
        assert img.in_memory
        with maybe_deprecated(meth_name):
            data_again = method()
        assert data is data_again
        # Check that caching refreshes for new floating point type.
        img.uncache()
        fdata = img.get_fdata()
        assert fdata.dtype == np.float64
        fdata[:] = 42
        fdata_back = img.get_fdata()
        assert_array_equal(fdata_back, 42)
        assert fdata_back.dtype == np.float64
        # New data dtype, no caching, doesn't use or alter cache
        fdata_new_dt = img.get_fdata(caching='unchanged', dtype='f4')
        # We get back the original read, not the modified cache
        # Allow for small rounding error when the data is scaled with 32-bit
        # factors, rather than 64-bit factors and then cast to float-32
        # Use rtol/atol from numpy.allclose
        assert_allclose(fdata_new_dt, proxy_data.astype('f4'), rtol=1e-05, atol=1e-08)
        assert fdata_new_dt.dtype == np.float32
        # The original cache stays in place, for default float64
        assert_array_equal(img.get_fdata(), 42)
        # And for not-default float32, because we haven't cached
        fdata_new_dt[:] = 43
        fdata_new_dt = img.get_fdata(caching='unchanged', dtype='f4')
        assert_allclose(fdata_new_dt, proxy_data.astype('f4'), rtol=1e-05, atol=1e-08)
        # Until we reset with caching='fill', at which point we
        # drop the original float64 cache, and have a float32 cache
        fdata_new_dt = img.get_fdata(caching='fill', dtype='f4')
        assert_allclose(fdata_new_dt, proxy_data.astype('f4'), rtol=1e-05, atol=1e-08)
        # We're using the cache, for dtype='f4' reads
        fdata_new_dt[:] = 43
        assert_array_equal(img.get_fdata(dtype='f4'), 43)
        # We've lost the cache for float64 reads (no longer 42)
        assert_array_equal(img.get_fdata(), proxy_data)

    def _check_array_interface(self, imaker, meth_name):
        for caching in (None, 'fill', 'unchanged'):
            self._check_array_caching(imaker, meth_name, caching)

    def _check_array_caching(self, imaker, meth_name, caching):
        img = imaker()
        method = getattr(img, meth_name)
        get_data_func = method if caching is None else partial(method, caching=caching)
        assert isinstance(img.dataobj, np.ndarray)
        assert img.in_memory
        with maybe_deprecated(meth_name):
            data = get_data_func()
        # Returned data same object as underlying dataobj if using
        # old ``get_data`` method, or using newer ``get_fdata``
        # method, where original array was float64.
        arr_dtype = img.dataobj.dtype
        dataobj_is_data = arr_dtype == np.float64 or method == img.get_data
        # Set something to the output array.
        data[:] = 42
        with maybe_deprecated(meth_name):
            get_result_changed = np.all(get_data_func() == 42)
        assert get_result_changed == (dataobj_is_data or caching != 'unchanged')
        if dataobj_is_data:
            assert data is img.dataobj
            # Changing array data changes
            # data
            assert_array_equal(np.asarray(img.dataobj), 42)
            # Uncache has no effect
            img.uncache()
            with maybe_deprecated(meth_name):
                assert_array_equal(get_data_func(), 42)
        else:
            assert not data is img.dataobj
            assert not np.all(np.asarray(img.dataobj) == 42)
            # Uncache does have an effect
            img.uncache()
            with maybe_deprecated(meth_name):
                assert not np.all(get_data_func() == 42)
        # in_memory is always true for array images, regardless of
        # cache state.
        img.uncache()
        assert img.in_memory
        if meth_name != 'get_fdata':
            return
        # Return original array from get_fdata only if the input array is the
        # requested dtype.
        float_types = np.sctypes['float']
        if arr_dtype not in float_types:
            return
        for float_type in float_types:
            with maybe_deprecated(meth_name):
                data = get_data_func(dtype=float_type)
            assert (data is img.dataobj) == (arr_dtype == float_type)

    def validate_shape(self, imaker, params):
        # Validate shape
        img = imaker()
        # Same as expected shape
        assert img.shape == params['shape']
        # Same as array shape if passed
        if 'data' in params:
            assert img.shape == params['data'].shape
        # Read only
        with pytest.raises(AttributeError):
            img.shape = np.eye(4)

    def validate_ndim(self, imaker, params):
        # Validate shape
        img = imaker()
        # Same as expected ndim
        assert img.ndim == len(params['shape'])
        # Same as array ndim if passed
        if 'data' in params:
            assert img.ndim == params['data'].ndim
        # Read only
        with pytest.raises(AttributeError):
            img.ndim = 5

    def validate_mmap_parameter(self, imaker, params):
        img = imaker()
        fname = img.get_filename()
        with InTemporaryDirectory():
            # Load test files with mmap parameters
            # or
            # Save a generated file so we can test it
            if fname is None:
                # Skip only formats we can't write
                if not img.rw or not img.valid_exts:
                    return
                fname = 'image' + img.valid_exts[0]
                img.to_filename(fname)
            rt_img = img.__class__.from_filename(fname, mmap=True)
            assert_almost_equal(img.get_fdata(), rt_img.get_fdata())
            rt_img = img.__class__.from_filename(fname, mmap=False)
            assert_almost_equal(img.get_fdata(), rt_img.get_fdata())
            rt_img = img.__class__.from_filename(fname, mmap='c')
            assert_almost_equal(img.get_fdata(), rt_img.get_fdata())
            rt_img = img.__class__.from_filename(fname, mmap='r')
            assert_almost_equal(img.get_fdata(), rt_img.get_fdata())
            # r+ is specifically not valid for images
            with pytest.raises(ValueError):
                img.__class__.from_filename(fname, mmap='r+')
            with pytest.raises(ValueError):
                img.__class__.from_filename(fname, mmap='invalid')
            del rt_img  # to allow windows to delete the directory


class HeaderShapeMixin:
    """Tests that header shape can be set and got

    Add this one of your header supports ``get_data_shape`` and
    ``set_data_shape``.
    """

    def validate_header_shape(self, imaker, params):
        # Change shape in header, check this changes img.header
        img = imaker()
        hdr = img.header
        shape = hdr.get_data_shape()
        new_shape = (shape[0] + 1,) + shape[1:]
        hdr.set_data_shape(new_shape)
        assert img.header is hdr
        assert img.header.get_data_shape() == new_shape


class AffineMixin:
    """Adds test of affine property, method

    Add this one if your image has an ``affine`` property.
    """

    def validate_affine(self, imaker, params):
        # Check affine API
        img = imaker()
        assert_almost_equal(img.affine, params['affine'], 6)
        assert img.affine.dtype == np.float64
        img.affine[0, 0] = 1.5
        assert img.affine[0, 0] == 1.5
        # Read only
        with pytest.raises(AttributeError):
            img.affine = np.eye(4)


class SerializeMixin:
    def validate_to_from_stream(self, imaker, params):
        img = imaker()
        klass = getattr(self, 'klass', img.__class__)
        stream = io.BytesIO()
        img.to_stream(stream)

        rt_img = klass.from_stream(stream)
        assert self._header_eq(img.header, rt_img.header)
        assert np.array_equal(img.get_fdata(), rt_img.get_fdata())

    def validate_file_stream_equivalence(self, imaker, params):
        img = imaker()
        klass = getattr(self, 'klass', img.__class__)
        with InTemporaryDirectory():
            fname = 'img' + self.standard_extension
            img.to_filename(fname)

            with open('stream', 'wb') as fobj:
                img.to_stream(fobj)

            # Check that writing gets us the same thing
            contents1 = pathlib.Path(fname).read_bytes()
            contents2 = pathlib.Path('stream').read_bytes()
            assert contents1 == contents2

            # Check that reading gets us the same thing
            img_a = klass.from_filename(fname)
            with open(fname, 'rb') as fobj:
                img_b = klass.from_stream(fobj)
                # This needs to happen while the filehandle is open
                assert np.array_equal(img_a.get_fdata(), img_b.get_fdata())
            assert self._header_eq(img_a.header, img_b.header)
            del img_a
            del img_b

    def validate_to_from_bytes(self, imaker, params):
        img = imaker()
        klass = getattr(self, 'klass', img.__class__)
        with InTemporaryDirectory():
            fname = 'img' + self.standard_extension
            img.to_filename(fname)

            all_images = list(getattr(self, 'example_images', [])) + [{'fname': fname}]
            for img_params in all_images:
                img_a = klass.from_filename(img_params['fname'])
                bytes_a = img_a.to_bytes()

                img_b = klass.from_bytes(bytes_a)

                assert img_b.to_bytes() == bytes_a
                assert self._header_eq(img_a.header, img_b.header)
                assert np.array_equal(img_a.get_fdata(), img_b.get_fdata())
                del img_a
                del img_b

    @pytest.fixture(autouse=True)
    def setup_method(self, httpserver, tmp_path):
        """Make pytest fixtures available to validate functions"""
        self.httpserver = httpserver
        self.tmp_path = tmp_path

    def validate_from_url(self, imaker, params):
        server = self.httpserver

        img = imaker()
        img_bytes = img.to_bytes()

        server.expect_oneshot_request('/img').respond_with_data(img_bytes)
        url = server.url_for('/img')
        assert url.startswith('http://')  # Check we'll trigger an HTTP handler
        rt_img = img.__class__.from_url(url)

        assert rt_img.to_bytes() == img_bytes
        assert self._header_eq(img.header, rt_img.header)
        assert np.array_equal(img.get_fdata(), rt_img.get_fdata())
        del img
        del rt_img

    def validate_from_file_url(self, imaker, params):
        tmp_path = self.tmp_path

        img = imaker()
        import uuid

        fname = tmp_path / f'img-{uuid.uuid4()}{self.standard_extension}'
        img.to_filename(fname)

        rt_img = img.__class__.from_url(f'file:///{fname}')

        assert self._header_eq(img.header, rt_img.header)
        assert np.array_equal(img.get_fdata(), rt_img.get_fdata())
        del img
        del rt_img

    @staticmethod
    def _header_eq(header_a, header_b):
        """Header equality check that can be overridden by a subclass of this test

        This allows us to retain the same tests above when testing an image that uses an
        abstract class as a header, namely when testing the FileBasedImage API, which
        raises a NotImplementedError for __eq__
        """
        return header_a == header_b


class LoadImageAPI(
    GenericImageAPI, DataInterfaceMixin, AffineMixin, GetSetDtypeMixin, HeaderShapeMixin
):
    # Callable returning an image from a filename
    loader = None
    # Sequence of dictionaries, where dictionaries have keys
    # 'fname" in addition to keys for ``params`` (see obj_params docstring)
    example_images = ()
    # Class of images to be tested
    klass = None

    def obj_params(self):
        for img_params in self.example_images:
            yield lambda: self.loader(img_params['fname']), img_params

    def validate_path_maybe_image(self, imaker, params):
        for img_params in self.example_images:
            test, sniff = self.klass.path_maybe_image(img_params['fname'])
            assert isinstance(test, bool)
            if sniff is not None:
                assert isinstance(sniff[0], bytes)
                assert isinstance(sniff[1], str)


class MakeImageAPI(LoadImageAPI):
    """Validation for images we can make with ``func(data, affine, header)``"""

    # A callable returning an image from ``image_maker(data, affine, header)``
    image_maker = None
    # A callable returning a header from ``header_maker()``
    header_maker = None
    # Example shapes for created images
    example_shapes = ((2,), (2, 3), (2, 3, 4), (2, 3, 4, 5))
    # Supported dtypes for storing to disk
    storable_dtypes = (np.uint8, np.int16, np.float32)

    def obj_params(self):
        # Return any obj_params from superclass
        for func, params in super().obj_params():
            yield func, params
        # Create new images
        aff = np.diag([1, 2, 3, 1])

        def make_imaker(arr, aff, header=None):
            return lambda: self.image_maker(arr, aff, header)

        def make_prox_imaker(arr, aff, hdr):
            def prox_imaker():
                img = self.image_maker(arr, aff, hdr)
                rt_img = bytesio_round_trip(img)
                return self.image_maker(rt_img.dataobj, aff, rt_img.header)

            return prox_imaker

        for shape, stored_dtype in product(self.example_shapes, self.storable_dtypes):
            # To make sure we do not trigger scaling, always use the
            # stored_dtype for the input array.
            arr = np.arange(np.prod(shape), dtype=stored_dtype).reshape(shape)
            hdr = self.header_maker()
            hdr.set_data_dtype(stored_dtype)
            func = make_imaker(arr.copy(), aff, hdr)
            params = dict(dtype=stored_dtype, affine=aff, data=arr, shape=shape, is_proxy=False)
            yield make_imaker(arr.copy(), aff, hdr), params
            if not self.can_save:
                continue
            # Create proxy images from these array images, by storing via BytesIO.
            # We assume that loading from a fileobj creates a proxy image.
            params['is_proxy'] = True
            yield make_prox_imaker(arr.copy(), aff, hdr), params


class DtypeOverrideMixin(GetSetDtypeMixin):
    """Test images that can accept ``dtype`` arguments to ``__init__`` and
    ``to_file_map``
    """

    def validate_init_dtype_override(self, imaker, params):
        img = imaker()
        klass = img.__class__
        for dtype in self.storable_dtypes:
            if hasattr(img, 'affine'):
                new_img = klass(img.dataobj, img.affine, header=img.header, dtype=dtype)
            else:  # XXX This is for CIFTI-2, these validators might need refactoring
                new_img = klass(img.dataobj, header=img.header, dtype=dtype)
            assert new_img.get_data_dtype() == dtype

            if self.has_scaling and self.can_save:
                with np.errstate(invalid='ignore'):
                    rt_img = bytesio_round_trip(new_img)
                assert rt_img.get_data_dtype() == dtype

    def validate_to_file_dtype_override(self, imaker, params):
        if not self.can_save:
            raise unittest.SkipTest
        img = imaker()
        orig_dtype = img.get_data_dtype()
        fname = 'image' + self.standard_extension
        with InTemporaryDirectory():
            for dtype in self.storable_dtypes:
                try:
                    img.to_filename(fname, dtype=dtype)
                except WriterError:
                    # It's possible to try to save to a dtype that requires
                    # scaling, and images without scale factors will fail.
                    # We're not testing that here.
                    continue
                rt_img = img.__class__.from_filename(fname)
                assert rt_img.get_data_dtype() == dtype
                assert img.get_data_dtype() == orig_dtype


class ImageHeaderAPI(MakeImageAPI):
    """When ``self.image_maker`` is an image class, make header from class"""

    def header_maker(self):
        return self.image_maker.header_class()


class TestSpatialImageAPI(ImageHeaderAPI):
    klass = image_maker = SpatialImage
    can_save = False


class TestAnalyzeAPI(TestSpatialImageAPI, DtypeOverrideMixin):
    """General image validation API instantiated for Analyze images"""

    klass = image_maker = AnalyzeImage
    has_scaling = False
    can_save = True
    standard_extension = '.img'
    # Supported dtypes for storing to disk
    storable_dtypes = (np.uint8, np.int16, np.int32, np.float32, np.float64)


class TestSpm99AnalyzeAPI(TestAnalyzeAPI):
    # SPM-type analyze need scipy for mat file IO
    klass = image_maker = Spm99AnalyzeImage
    has_scaling = True
    can_save = have_scipy


class TestSpm2AnalyzeAPI(TestSpm99AnalyzeAPI):
    klass = image_maker = Spm2AnalyzeImage


class TestNifti1PairAPI(TestSpm99AnalyzeAPI):
    klass = image_maker = Nifti1Pair
    can_save = True


class TestNifti1API(TestNifti1PairAPI, SerializeMixin):
    klass = image_maker = Nifti1Image
    standard_extension = '.nii'


class TestNifti2PairAPI(TestNifti1PairAPI):
    klass = image_maker = Nifti2Pair


class TestNifti2API(TestNifti1API):
    klass = image_maker = Nifti2Image


class TestMinc1API(ImageHeaderAPI):
    klass = image_maker = Minc1Image
    loader = minc1.load
    example_images = MINC1_EXAMPLE_IMAGES


class TestMinc2API(TestMinc1API):
    def setup_method(self):
        if not have_h5py:
            raise unittest.SkipTest('Need h5py for these tests')

    klass = image_maker = Minc2Image
    loader = minc2.load
    example_images = MINC2_EXAMPLE_IMAGES


class TestPARRECAPI(LoadImageAPI):
    def loader(self, fname):
        return parrec.load(fname)

    klass = parrec.PARRECImage
    example_images = PARREC_EXAMPLE_IMAGES


# ECAT is a special case and needs more thought
# class TestEcatAPI(TestAnalyzeAPI):
#     image_maker = ecat.EcatImage
#     has_scaling = True
#     can_save = True
#    standard_extension = '.v'


class TestMGHAPI(ImageHeaderAPI, SerializeMixin):
    klass = image_maker = MGHImage
    example_shapes = ((2, 3, 4), (2, 3, 4, 5))  # MGH can only do >= 3D
    has_scaling = True
    can_save = True
    standard_extension = '.mgh'


class TestGiftiAPI(LoadImageAPI, SerializeMixin):
    klass = image_maker = GiftiImage
    can_save = True
    standard_extension = '.gii'


class TestAFNIAPI(LoadImageAPI):
    loader = brikhead.load
    klass = image_maker = brikhead.AFNIImage
    example_images = AFNI_EXAMPLE_IMAGES
