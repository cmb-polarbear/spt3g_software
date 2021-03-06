from spt3g import core
from spt3g.calibration import BolometerProperties, BolometerPropertiesMap
from spt3g.calibration import PointingProperties, PointingPropertiesMap
import numpy, scipy.stats, os, re

'''
Utilities for bringing together calibration data from a number of sources
to produce unified calibration data to go in folders with the data for
analysis processing.
'''

@core.indexmod
class BuildBoloPropertiesMap(object):
    '''
    Build bolometer properties map from raw calibration sub-frames emitted
    by other processing scripts. Input data are maps of bolo ID to floats
    or, in the case of names, strings. If multiple instance of each data
    class appear, the final bolometer properties map will be the median
    of the input values.

    Expects to be passed frames from:
    - RCW38 Relative Pointing Offset Calibration (Keys: 'PointingOffsetX', 'PointingOffsetY')
    - CenA Angle Calibration (Keys: 'PolarizationAngle', 'PolarizationEfficiency')
    - Band Calibration (Key: 'BoloBands')
    - Physical Name Data (Key: 'PhysicalBoloIDs')
    '''
    
    def __init__(self, drop_original_frames=True, filter_abs_point=False):
        '''
        If drop_original_frames is True, will drop all input Calibration frames.

        If filter_abs_point is True, will attempt to compensate for telescope
        motion by centering the source on the focal plane. Note that this is less
        robust than having real offline pointing and should only be used in
        desperation.
        '''

        self.drop_original_frames = drop_original_frames
        self.filter_abs_point = filter_abs_point

        self.props = {}

    def __call__(self, frame):
        if frame.type == core.G3FrameType.EndProcessing:
            boloprops = BolometerPropertiesMap()

            # Technique to average together points while ignoring outliers
            def robust_avg(data):
                data = numpy.asarray(data)[numpy.isfinite(data)]
                if len(data) == 1:
                    return data[0]
                return numpy.mean(scipy.stats.sigmaclip(data, low=2.5, high=2.5)[0])

            for bolo in self.props.keys():
                p = BolometerProperties()

                if 'xoffsets' in self.props[bolo]:
                    # Ideally we would have error bars on these measurements...
                    p.x_offset = robust_avg(self.props[bolo]['xoffsets'])
                    p.y_offset = robust_avg(self.props[bolo]['yoffsets'])

                if 'physname' in self.props[bolo]:
                    p.physical_name = self.props[bolo]['physname']

                if 'band' in self.props[bolo]:
                    p.band = self.props[bolo]['band']

                if 'polangle' in self.props[bolo]:
                    # Ideally we would have error bars on these measurements.

                    # Strategy: to avoid wraparound issues, form a 2-D vector
                    # and then take the median X/Y position
                    # XXX: Do anything about vectors being headless?
                    angles = numpy.asarray(self.props[bolo]['polangle'])
                    efficiencies = numpy.asarray(self.props[bolo]['poleff'])
                    poly = robust_avg(numpy.sin(angles/core.G3Units.rad)*efficiencies)
                    polx = robust_avg(numpy.cos(angles/core.G3Units.rad)*efficiencies)
                    p.pol_angle = numpy.arctan2(poly, polx)
                    p.pol_efficiency = numpy.hypot(poly, polx)

                if 'pixel_id' in self.props[bolo]:
                    p.pixel_id = self.props[bolo]['pixel_id']
                if 'wafer_id' in self.props[bolo]:
                    p.wafer_id = self.props[bolo]['wafer_id']
                
                boloprops[bolo] = p

            cframe = core.G3Frame(core.G3FrameType.Calibration)
            cframe['BolometerProperties'] = boloprops
            return [cframe, frame]

        # Pointing calibration
        if 'PointingOffsetX' in frame:
            xshift = yshift = 0.

            if self.filter_abs_point:
                # XXX: this algorithm is dubious and universally worse than
                # correct boresight pointing
                xshift = numpy.nanmedian(frame['PointingOffsetX'].values())
                yshift = numpy.nanmedian(frame['PointingOffsetY'].values())

            for bolo in frame['PointingOffsetX'].keys():
                if bolo not in self.props:
                    self.props[bolo] = {}
                if 'xoffsets' not in self.props[bolo]:
                    self.props[bolo]['xoffsets'] = []
                    self.props[bolo]['yoffsets'] = []

                self.props[bolo]['xoffsets'].append(frame['PointingOffsetX'][bolo] - xshift)
                self.props[bolo]['yoffsets'].append(frame['PointingOffsetY'][bolo] - yshift)

        # Band calibration
        if 'BoloBands' in frame:
            for bolo in frame['BoloBands'].keys():
                if bolo not in self.props:
                    self.props[bolo] = {}
                #assert('band' not in self.props[bolo] or self.props[bolo]['band'] == frame['BoloBands'][bolo])
                self.props[bolo]['band'] = frame['BoloBands'][bolo]

        # Names
        if 'PhysicalBoloIDs' in frame:
            for bolo in frame['PhysicalBoloIDs'].keys():
                if bolo not in self.props:
                    self.props[bolo] = {}
                #assert('physname' not in self.props[bolo] or self.props[bolo]['physname'] == frame['PhysicalBoloIDs'][bolo])
                self.props[bolo]['physname'] = frame['PhysicalBoloIDs'][bolo]

        if 'PixelIDs' in frame:
            for bolo in frame['PixelIDs'].keys():
                if bolo not in self.props:
                    self.props[bolo] = {}
                #assert('pixel_id' not in self.props[bolo] or self.props[bolo]['pixel_id'] == frame['PixelIDs'][bolo])
                self.props[bolo]['pixel_id'] = frame['PixelIDs'][bolo]

        if 'WaferIDs' in frame:
            for bolo in frame['WaferIDs'].keys():
                if bolo not in self.props:
                    self.props[bolo] = {}
                #assert('wafer_id' not in self.props[bolo] or self.props[bolo]['wafer_id'] == frame['WaferIDs'][bolo])
                self.props[bolo]['wafer_id'] = frame['WaferIDs'][bolo]

        # Polarization Angles
        if 'PolarizationAngle' in frame:
            for bolo in frame['PolarizationAngle'].keys():
                if bolo not in self.props:
                    self.props[bolo] = {}
                if 'polangle' not in self.props[bolo]:
                    self.props[bolo]['polangle'] = []
                    self.props[bolo]['poleff'] = []

                self.props[bolo]['polangle'].append(frame['PolarizationAngle'][bolo])
                self.props[bolo]['poleff'].append(frame['PolarizationEfficiency'][bolo])

        if frame.type == core.G3FrameType.Calibration and self.drop_original_frames:
            return []

@core.indexmod
def ExplodeBolometerProperties(frame, bpmname='NominalBolometerProperties'):
    '''
    Take a bolometer properties map (usually the nominal one) and convert it
    into its constituent keys as though they came from real calibration. This
    is the inverse of BuildBoloPropertiesMap and mostly is useful when combining
    hardware map information with real calibration.
    '''

    if bpmname not in frame:
        return

    bpm = frame[bpmname]
    polangle = core.G3MapDouble()
    poleff = core.G3MapDouble()
    bands = core.G3MapDouble()
    names = core.G3MapString()
    pixels = core.G3MapString()
    wafers = core.G3MapString()
    xoff = core.G3MapDouble()
    yoff = core.G3MapDouble()

    for bolo, p in bpm.iteritems():
        polangle[bolo] = p.pol_angle
        poleff[bolo] = p.pol_efficiency
        bands[bolo] = p.band
        names[bolo] = p.physical_name
        xoff[bolo] = p.x_offset
        yoff[bolo] = p.y_offset
        pixels[bolo] = p.pixel_id
        wafers[bolo] = p.wafer_id

    frame['PolarizationAngle'] = polangle
    frame['PolarizationEfficiency'] = poleff
    frame['PhysicalBoloIDs'] = names
    frame['BoloBands'] = bands
    frame['PointingOffsetX'] = xoff
    frame['PointingOffsetY'] = yoff
    frame['PixelIDs'] = pixels
    frame['WaferIDs'] = wafers

@core.indexmod
class BuildPointingProperties(object):
    '''
    Build pointing properties from raw calibration sub-frames emitted
    by other processing scripts. Input data are floats, including
    tilt information, and eventually other pointing model values.

    Expects to be passed frames from:
    - Az tilt fit parameters (Keys: 'tiltAngle', 'tiltHA', 'tiltLat', 'tiltMag')
    '''
    
    def __init__(self, drop_original_frames=True):
        '''
        If drop_original_frames is True, will drop all input Calibration frames.
        '''

        self.drop_original_frames = drop_original_frames

        self.props = {}

    def __call__(self, frame):
        if frame.type == core.G3FrameType.EndProcessing:
            pointingprops = PointingPropertiesMap()

            p = PointingProperties()

            if 'tiltLat' in self.props:
                p['tiltLat'] = self.props['tiltLat']

            if 'tiltHA' in self.props:
                p['tiltHA'] = self.props['tiltHA']
            
            if 'tiltMag' in self.props:
                p['tiltMag'] = self.props['tiltMag']
            
            if 'tiltAngle' in self.props:
                p['tiltAngle'] = self.props['tiltAngle']

        if frame.type == core.G3FrameType.Calibration and self.drop_original_frames:
            return []

@core.indexmod
class MergeCalibrationFrames(object):
    '''
    Merge the keys from a sequence of calibration frames. Will throw an
    exception if a key recurs in more than one calibration frame. The merged
    calibration frame will be emitted before the first non-calibration frame
    that follows a calibration frame or at the end of processing, whichever
    comes first. Other non-calibration frames will be ignored.
    '''
    def __init__(self, KeysToIgnore=['PointingOffsetX', 'PointingOffsetY']):
        '''
        Ignores keys in the KeysToIgnore list during merging. By default, set
        to values written by the flux/pointing calibration that are stored to
        the BolometerPropertiesMap.
        '''
        self.outframe = core.G3Frame(core.G3FrameType.Calibration)
        self.ignore_keys = KeysToIgnore
    def __call__(self, frame):
        if frame.type == core.G3FrameType.Calibration:
            for k in frame.keys():
                if k not in self.ignore_keys:
                    self.outframe[k] = frame[k]
            return []

        # Ignore random wiring frames etc.
        if self.outframe is None or len(self.outframe.keys()) == 0:
            return

        # Return merged frame before whatever follows if we have new data
        out = [self.outframe, frame]
        self.outframe = None
        return out

