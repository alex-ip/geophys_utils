'''
Created on 14Sep.,2016

@author: Alex
'''
import numpy as np
import math
from scipy.ndimage import map_coordinates
from geophys_utils._crs_utils import get_utm_crs, transform_coords
from geophys_utils._transect_utils import sample_transect


class NetCDFGridUtils(object):
    '''
    NetCDFGridUtils class to do various fiddly things with gridded NetCDF geophysics files.
    '''
    # Assume WGS84 lat/lon if no CRS is provided
    DEFAULT_CRS = "GEOGCS[\"WGS 84\",DATUM[\"WGS_1984\",SPHEROID[\"WGS 84\",6378137,298.257223563,AUTHORITY[\"EPSG\",\"7030\"]],AUTHORITY[\"EPSG\",\"6326\"]],PRIMEM[\"Greenwich\",0,AUTHORITY[\"EPSG\",\"8901\"]],UNIT[\"degree\",0.0174532925199433,AUTHORITY[\"EPSG\",\"9122\"]],AUTHORITY[\"EPSG\",\"4326\"]]"
    HORIZONTAL_VARIABLE_NAMES = ['lon', 'Easting', 'x', 'longitude']
    DEFAULT_MAX_BYTES = 500000000  # Default to 500,000,000 bytes for NCI's OPeNDAP
    FLOAT_TOLERANCE = 0.000001

    def __init__(self, netcdf_dataset):
        '''
        NetCDFGridUtils Constructor - wraps a NetCDF dataset
        '''
        def get_nominal_pixel_metres():
            '''
            Function to return a tuple with the nominal vertical and horizontal sizes of the centre pixel in metres
            '''
            centre_pixel_indices = [
                len(self.dimension_arrays[dim_index]) // 2 for dim_index in range(2)]

            # Get coordinates of centre pixel and next diagonal pixel
            centre_pixel_coords = [[self.dimension_arrays[dim_index][centre_pixel_indices[dim_index]] 
                                    for dim_index in range(2)],
                                   [self.dimension_arrays[dim_index][centre_pixel_indices[dim_index] + 1] 
                                    for dim_index in range(2)]
                                   ]

            if self.YX_order:
                for coord_index in range(2):
                    centre_pixel_coords[coord_index].reverse()

            nominal_utm_crs = get_utm_crs(centre_pixel_coords[0], self.crs)
            centre_pixel_utm_coords = transform_coords(
                centre_pixel_coords, from_crs=self.crs, to_crs=nominal_utm_crs)

            return [abs(centre_pixel_utm_coords[1][
                        dim_index] - centre_pixel_utm_coords[0][dim_index]) for dim_index in range(2)]

        def get_default_sample_metres():
            '''
            Function to return average nominal pixel size in metres rounded up to nearest 10^x or 5*10^x
            This is to provide a sensible default resolution for the sampling points along a transect by keeping it around the nominal pixel size
            '''
            log_10_avg_pixel_metres = math.log((self.nominal_pixel_metres[
                                               0] + self.nominal_pixel_metres[1]) / 2.0) / math.log(10.0)
            log_10_5 = math.log(5.0) / math.log(10.0)

            return round(math.pow(10.0, math.floor(log_10_avg_pixel_metres) +
                                  (log_10_5 if((log_10_avg_pixel_metres % 1.0) < log_10_5) else 1.0)))

        self.netcdf_dataset = netcdf_dataset

# assert len(self.netcdf_dataset.dimensions) == 2, 'NetCDF dataset must be
# 2D' # This is not valid

        # Find variable with "grid_mapping" attribute - assumed to be 2D data
        # variable
        try:
            self.data_variable = [variable for variable in self.netcdf_dataset.variables.values(
            ) if hasattr(variable, 'grid_mapping')][0]
        except:
            raise Exception(
                'Unable to determine data variable (must have "grid_mapping" attribute')

        # Boolean flag indicating YX array ordering
        # TODO: Find a nicer way of dealing with this
        self.YX_order = self.data_variable.dimensions[
            1] in NetCDFGridUtils.HORIZONTAL_VARIABLE_NAMES

        # Two-element list of dimension varibles.
        self.dimension_arrays = [self.netcdf_dataset.variables[dimension_name][
            :] for dimension_name in self.data_variable.dimensions]

        self.grid_mapping_variable = netcdf_dataset.variables[
            self.data_variable.grid_mapping]
        
        self.crs = self.grid_mapping_variable.spatial_ref

        self.GeoTransform = [float(
            number) for number in self.grid_mapping_variable.GeoTransform.strip().split(' ')]

        self.pixel_size = [abs(self.GeoTransform[1]),
                           abs(self.GeoTransform[5])]
        if self.YX_order:
            self.pixel_size.reverse()

        self.min_extent = tuple([min(self.dimension_arrays[
                                dim_index]) - self.pixel_size[dim_index] / 2.0 for dim_index in range(2)])
        self.max_extent = tuple([max(self.dimension_arrays[
                                dim_index]) + self.pixel_size[dim_index] / 2.0 for dim_index in range(2)])

        self.nominal_pixel_metres = get_nominal_pixel_metres()

        self.default_sample_metres = get_default_sample_metres()

    def get_indices_from_coords(self, coordinates, crs=None):
        '''
        Returns list of netCDF array indices corresponding to coordinates to support nearest neighbour queries
        @parameter coordinates: iterable collection of coordinate pairs or single coordinate pair
        @parameter crs: Coordinate Reference System for coordinates. None == native NetCDF CRS
        '''
        crs = crs or self.crs
        native_coordinates = transform_coords(coordinates, self.crs, crs)
        

        # Convert coordinates to same dimension ordering as array
        if self.YX_order:
            try:
                for coord_index in range(len(native_coordinates)):
                    if native_coordinates[coord_index] is not None:
                        native_coordinates[coord_index] = list(
                            native_coordinates[coord_index])
                        native_coordinates[coord_index].reverse()
            except TypeError:
                native_coordinates = list(native_coordinates)
                native_coordinates.reverse()
        try:  # Multiple coordinates
            indices = [[np.where(abs(self.dimension_arrays[dim_index] - coordinate[dim_index]) <= (self.pixel_size[dim_index] / 2.0))[0][0] for dim_index in range(2)]
                       if not ([True for dim_index in range(2) if coordinate[dim_index] < self.min_extent[dim_index] or coordinate[dim_index] > self.max_extent[dim_index]])
                       else None
                       for coordinate in native_coordinates]
        except TypeError:  # Single coordinate pair
            indices = ([np.where(abs(self.dimension_arrays[dim_index] - native_coordinates[dim_index]) <= (self.pixel_size[dim_index] / 2.0))[0][0] for dim_index in range(2)]
                       if not [True for dim_index in range(2) if native_coordinates[dim_index] < self.min_extent[dim_index] or native_coordinates[dim_index] > self.max_extent[dim_index]]
                       else None)

        return indices

    def get_fractional_indices_from_coords(self, coordinates, crs=None):
        '''
        Returns list of fractional array indices corresponding to coordinates to support interpolation
        @parameter coordinates: iterable collection of coordinate pairs or single coordinate pair
        @parameter crs: Coordinate Reference System for coordinates. None == native NetCDF CRS
        '''
        crs = crs or self.crs
        native_coordinates = transform_coords(coordinates, self.crs, crs)

        self.pixel_size

        # Convert coordinates to same order as array
        if self.YX_order:
            try:
                for coord_index in range(len(native_coordinates)):
                    if native_coordinates[coord_index] is not None:
                        native_coordinates[coord_index] = list(
                            native_coordinates[coord_index])
                        native_coordinates[coord_index].reverse()
            except:
                native_coordinates = list(native_coordinates)
                native_coordinates.reverse()
        # TODO: Make sure this still works with Southwards-positive datasets
        try:  # Multiple coordinates
            fractional_indices = [[(coordinate[dim_index] - min(self.dimension_arrays[dim_index])) / self.pixel_size[dim_index] for dim_index in range(2)]
                                  if not ([True for dim_index in range(2) if coordinate[dim_index] < self.min_extent[dim_index] or coordinate[dim_index] > self.max_extent[dim_index]])
                                  else None
                                  for coordinate in native_coordinates]
        except:  # Single coordinate pair
            fractional_indices = ([(native_coordinates[dim_index] - min(self.dimension_arrays[dim_index])) / self.pixel_size[dim_index] for dim_index in range(2)]
                                  if not [True for dim_index in range(2) if native_coordinates[dim_index] < self.min_extent[dim_index] or native_coordinates[dim_index] > self.max_extent[dim_index]]
                                  else None)

        return fractional_indices

    def get_value_at_coords(self, coordinates, crs=None,
                            max_bytes=None, variable_name=None):
        '''
        Returns list of array values at specified coordinates
        @parameter coordinates: iterable collection of coordinate pairs or single coordinate pair
        @parameter crs: Coordinate Reference System for coordinates. None == native NetCDF CRS
        @parameter max_bytes: Maximum number of bytes to read in a single query. Defaults to NetCDFGridUtils.DEFAULT_MAX_BYTES
        @parameter variable_name: NetCDF variable_name if not default data variable
        '''
        # Use arbitrary maximum request size of NetCDFGridUtils.DEFAULT_MAX_BYTES
        # (500,000,000 bytes => 11180 points per query)
        max_bytes = max_bytes or 100  # NetCDFGridUtils.DEFAULT_MAX_BYTES

        if variable_name:
            data_variable = self.netcdf_dataset.variables[variable_name]
        else:
            data_variable = self.data_variable

        no_data_value = data_variable._FillValue

        indices = self.get_indices_from_coords(coordinates, crs)

        # Allow for the fact that the NetCDF advanced indexing will pull back
        # n^2 cells rather than n
        max_points = max(
            int(math.sqrt(max_bytes / data_variable.dtype.itemsize)), 1)
        try:
            # Make this a vectorised operation for speed (one query for as many
            # points as possible)
            # Array of valid index pairs only
            index_array = np.array(
                [index_pair for index_pair in indices if index_pair is not None])
            assert len(index_array.shape) == 2 and index_array.shape[
                1] == 2, 'Not an iterable containing index pairs'
            # Boolean mask indicating which index pairs are valid
            mask_array = np.array([(index_pair is not None)
                                   for index_pair in indices])
            # Array of values read from variable
            value_array = np.ones(shape=(len(index_array)),
                                  dtype=data_variable.dtype) * no_data_value
            # Final result array including no-data for invalid index pairs
            result_array = np.ones(
                shape=(len(mask_array)), dtype=data_variable.dtype) * no_data_value
            start_index = 0
            end_index = min(max_points, len(index_array))
            while True:
                # N.B: ".diagonal()" is required because NetCDF doesn't do advanced indexing exactly like numpy
                # Hack is required to take values from leading diagonal. Requires n^2 elements retrieved instead of n. Not good, but better than whole array
                # TODO: Think of a better way of doing this
                value_array[start_index:end_index] = data_variable[
                    (index_array[start_index:end_index, 0], index_array[start_index:end_index, 1])].diagonal()
                if end_index == len(index_array):  # Finished
                    break
                start_index = end_index
                end_index = min(start_index + max_points, len(index_array))

            result_array[mask_array] = value_array
            return list(result_array)
        except:
            return data_variable[indices[0], indices[1]]

    def get_interpolated_value_at_coords(
            self, coordinates, crs=None, max_bytes=None, variable_name=None):
        '''
        Returns list of interpolated array values at specified coordinates
        @parameter coordinates: iterable collection of coordinate pairs or single coordinate pair
        @parameter crs: Coordinate Reference System for coordinates. None == native NetCDF CRS
        @parameter max_bytes: Maximum number of bytes to read in a single query. Defaults to NetCDFGridUtils.DEFAULT_MAX_BYTES
        @parameter variable_name: NetCDF variable_name if not default data variable
        '''
        # TODO: Check behaviour of scipy.ndimage.map_coordinates adjacent to no-data areas. Should not interpolate no-data value
        # TODO: Make this work for arrays > memory
        max_bytes = max_bytes or 100
        NetCDFGridUtils.DEFAULT_MAX_BYTES

        if variable_name:
            data_variable = self.netcdf_dataset.variables[variable_name]
        else:
            data_variable = self.data_variable

        no_data_value = data_variable._FillValue

        fractional_indices = self.get_fractional_indices_from_coords(
            coordinates, crs)

        # Make this a vectorised operation for speed (one query for as many
        # points as possible)
        try:
            # Array of valid index pairs only
            index_array = np.array(
                [index_pair for index_pair in fractional_indices if index_pair is not None])
            assert len(index_array.shape) == 2 and index_array.shape[
                1] == 2, 'Not an iterable containing index pairs'
            # Boolean mask indicating which index pairs are valid
            mask_array = np.array([(index_pair is not None)
                                   for index_pair in fractional_indices])
            # Array of values read from variable
            value_array = np.ones(shape=(len(index_array)),
                                  dtype=data_variable.dtype) * no_data_value
            # Final result array including no-data for invalid index pairs
            result_array = np.ones(
                shape=(len(mask_array)), dtype=data_variable.dtype) * no_data_value

            value_array = map_coordinates(
                data_variable, index_array.transpose(), cval=no_data_value)

            result_array[mask_array] = value_array

            # Mask out any coordinates falling in no-data areas. Need to do this to stop no-data value from being interpolated
            # This is a bit ugly.
            result_array[np.array(self.get_value_at_coords(
                coordinates, crs, max_bytes, variable_name)) == no_data_value] = no_data_value

            return list(result_array)
        except AssertionError:
            return map_coordinates(data_variable, np.array(
                [[fractional_indices[0]], [fractional_indices[1]]]), cval=no_data_value)


    def sample_transect(self, transect_vertices, crs=None, sample_metres=None):
        '''
        Function to return a list of sample points sample_metres apart along lines between transect vertices
        @param transect_vertices: list or array of transect vertex coordinates
        @param crs: coordinate reference system for transect_vertices
        @param sample_metres: distance between sample points in metres
        '''
        crs = crs or self.crs
        sample_metres = sample_metres or self.default_sample_metres
        return sample_transect(self, transect_vertices, crs, sample_metres)
        
