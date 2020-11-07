import os
import shutil
import ast
import datetime as dt
import numpy as np
import pandas as pd
import arcpy


class Toolbox:
    def __init__(self):
        self.label = "Transit Accessibility Analyst"
        self.alias = "TAA"

        # List of tool classes associated with this toolbox
        self.tools = [
            CreateNetwork, 
            DefineOD,
            MeasureAccessibility, 
            ProposeNewRoute
        ]


class CreateNetwork:
    def __init__(self):
        self.label = "1. Create Network Dataset"
        self.description = ""
        self.canRunInBackground = False

    @staticmethod
    def getParameterInfo():
        param0 = arcpy.Parameter(
            displayName="GTFS Folder",
            name="gtfs_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )

        param1 = arcpy.Parameter(
            displayName="Street Feature Class",
            name='street_fc',
            datatype='GPFeatureLayer',
            parameterType='Required',
            direction='Input'
        )
        param1.filter.list = ['Polyline']

        param2 = arcpy.Parameter(
            displayName='Road Class Field (Optional)',
            name='road_class',
            datatype='Field',
            parameterType='Optional',
            direction='Input'
        )
        param2.parameterDependencies = [param1.name]
        param2.filter.list = ['Short', 'Long', 'Text']

        param3 = arcpy.Parameter(
            displayName='Query Pedestrian-Restricted Roads',
            name='restrict_ped',
            datatype='GPSQLExpression',
            parameterType='Optional',
            direction='Input'
        )
        param3.parameterDependencies = [param1.name]

        param4 = arcpy.Parameter(
            displayName='Distance Threshold of Stops Getting Snapped',
            name='snap_dist',
            datatype='GPLinearUnit',
            parameterType='Required',
            direction='Input'
        )
        param4.value = '75 Meters'

        param5 = arcpy.Parameter(
            displayName='Network Template',
            name='nw_template',
            datatype='DEFile',
            parameterType='Required',
            direction='Input'
        )
        param5.filter.list = ['xml']

        param6 = arcpy.Parameter(
            displayName='Output Feature Dataset',
            name='fd',
            datatype='DEFeatureDataset',
            parameterType='Required',
            direction='Output'
        )

        return [param0, param1, param2, param3, param4, param5, param6]

    @staticmethod
    def updateParameters(param):
        return

    @staticmethod
    def isLicensed():
        try:
            if arcpy.CheckExtension("network") != "Available":
                raise ImportError
        except ImportError:
            return False
        return True

    @staticmethod
    def execute(param, msg):
        gtfs_folder = param[0].valueAsText
        street_fc = param[1].valueAsText
        road_cls = param[2].valueAsText
        restrict_ped = param[3].valueAsText
        snap_dist = param[4].valueAsText
        nw_template = param[5].valueAsText
        fd = param[6].valueAsText

        road_class = 'ROAD_CLASS'
        restrict_pedestrians = 'RestrictPedestrians'
        nw_streets = 'Streets'
        nw_stops = 'Stops'
        nw_line_variant_elements = 'LineVariantElements'
        nw_stops_on_streets = 'StopsOnStreets'
        nw_stop_connectors = 'StopConnectors'

        nd_check_list = [
            nw_streets, 
            nw_stops, 
            nw_line_variant_elements,
            nw_stops_on_streets, 
            nw_stop_connectors
        ]

        fd_path, fd_name = os.path.split(fd)
        arcpy.CreateFeatureDataset_management(
            fd_path, fd_name, street_fc
        )

        arcpy.env.workspace = fd_path

        for dataset in arcpy.ListDatasets():
            arcpy.env.workspace = os.path.join(fd_path, dataset)
            nds = arcpy.ListDatasets(feature_type='Network')
            if nds:
                for nd in nds:
                    nd_full_path = os.path.join(fd_path, dataset, nd)
                    nd_desc = arcpy.Describe(nd_full_path)
                    if np.any([source.name in nd_check_list
                               for source in nd_desc.sources]):
                        arcpy.Delete_management(nd_full_path)
                        msg.addMessage(f'Delete conflicting network dataset, '
                                       f'{nd}, within the workspace.')

        arcpy.env.workspace = fd_path

        for fc in nd_check_list:
            fc = os.path.join(fd_path, fc)
            if arcpy.Exists(fc):
                arcpy.Delete_management(fc)
                msg.addMessage(f'Delete existing data: "{fc}".')

        arcpy.GTFSToNetworkDatasetTransitSources_conversion(
            gtfs_folder, fd, interpolate=True
        )
        fms = arcpy.FieldMappings()

        if road_cls and road_cls != road_class:
            arcpy.CalculateField_management(
                street_fc, road_class, 
                f'!{road_cls}!', 
                field_type='SHORT'
            )
            fm_road_cls = arcpy.FieldMap()
            fm_road_cls.addInputField(street_fc, road_class)
            fms.addFieldMap(fm_road_cls)

        if restrict_ped:
            restrict_ped_field = restrict_ped.split(' = ')[0]
            if restrict_ped_field != restrict_pedestrians:
                fm_restrict_ped = arcpy.FieldMap()
                fm_restrict_ped.addInputField(street_fc, 
                                              restrict_ped_field)
                fms.addFieldMap(fm_restrict_ped)

        arcpy.FeatureClassToFeatureClass_conversion(
            street_fc, fd, 
            nw_streets, 
            field_mapping=fms
        )
        fd_street_fc = os.path.join(fd, nw_streets)

        if not arcpy.ListFields(fd_street_fc, road_class, 'SmallInteger'):
            try:
                arcpy.AddField_management(
                    fd_street_fc, 
                    road_class, 
                    'SHORT'
                )
            except arcpy.ExecuteError:
                raise TypeError(
                    f'Field type error {road_class}'
                    f'must be of "Short"'
                )

        if not arcpy.ListFields(fd_street_fc, restrict_pedestrians, 'String'):
            try:
                arcpy.AddField_management(
                    fd_street_fc, 
                    restrict_pedestrians, 
                    'TEXT', field_length=10
                )
            except arcpy.ExecuteError:
                raise TypeError(
                    f'Field type error {restrict_pedestrians} '
                    f'must be of "TEXT".'
                )
                
        arcpy.ConnectNetworkDatasetTransitSourcesToStreets_conversion(
            fd, fd_street_fc, snap_dist, restrict_ped
        )

        arcpy.CreateNetworkDatasetFromTemplate_na(nw_template, fd)
        # arcpy.BuildNetwork_na(os.path.join(fd, 'TransitNetwork_ND'))
        return


class DefineOD:
    def __init__(self):
        self.label = "2. Define Origin and Destination"
        self.description = ('Defining the origin and destination layer for '
                            'the accessibility analysis.')
        self.canRunInBackground = False

    def getParameterInfo(self):
        param0 = arcpy.Parameter(
            displayName='Study Zones',
            name='study_zone',
            datatype='GPFeatureLayer',
            parameterType='Required',
            direction='Input'
        )
        param0.filter.list = ['Polygon']

        param1 = arcpy.Parameter(
            displayName='Zone Unique ID',
            name='zone_id',
            datatype='Field',
            parameterType='Required',
            direction='Input'
        )
        param1.parameterDependencies = [param0.name]

        param2 = arcpy.Parameter(
            displayName='Opportunity Points',
            name='op_pnt',
            datatype='GPFeatureLayer',
            parameterType='Required',
            direction='Input'
        )
        param2.filter.list = ['Point']

        param3 = arcpy.Parameter(
            displayName='Opportunity Unique ID',
            name='op_id',
            datatype='Field',
            parameterType='Required',
            direction='Input'
        )
        param3.parameterDependencies = [param2.name]

        param4 = arcpy.Parameter(
            displayName='Output Feature Dataset from Step One',
            name='transit_nw_fd',
            datatype='DEFeatureDataset',
            parameterType='Required',
            direction='Input'
        )

        param5 = arcpy.Parameter(
            displayName='Travel Time Limit (in minutes)',
            name='time_limit_total',
            datatype='GPDouble',
            parameterType='Optional',
            direction='Input',
            category='Restrictions'
        )
        param5.value = 120

        param6 = arcpy.Parameter(
            displayName='Walk Time Limit (in minutes)',
            name='time_limit_walk',
            datatype='GPDouble',
            parameterType='Optional',
            direction='Input',
            category='Restrictions'
        )
        param6.value = 10

        param7 = arcpy.Parameter(
            displayName='Residential Locations',
            name='res_loc',
            datatype='GPFeatureLayer',
            parameterType='Optional',
            direction='Input',
            category='Restrictions'
        )
        param7.filter.list = ['Point', 'Polygon']

        param8 = arcpy.Parameter(
            displayName='Residential Locations Unique ID',
            name='res_loc_id',
            datatype='Field',
            parameterType='Optional',
            direction='Input',
            category='Restrictions'
        )
        param8.parameterDependencies = [param7.name]

        param9 = arcpy.Parameter(
            displayName='Time of Day',
            name='time_of_day',
            datatype='GPDate',
            parameterType='Optional',
            direction='Input',
            category='Time of Day'
        )

        param10 = arcpy.Parameter(
            displayName='Time Zone',
            name='time_zone',
            datatype='GPString',
            parameterType='Optional',
            direction='Input',
            category='Time of Day'
        )
        param10.filter.list = ['LOCAL_TIME_AT_LOCATIONS', 'UTC']
        param10.value = param10.filter.list[0]

        param11 = arcpy.Parameter(
            displayName='Accumulate Attributes',
            name='accum_attr',
            datatype='GPString',
            parameterType='Optional',
            direction='Input',
            multiValue=True
        )
        param11.filter.type = 'ValueList'
        param11.filter.list = ['Length (for reference only)',
                               'PublicTransitTime',
                               'WalkTime (for reference only)']
        param11.value = param11.filter.list[:2]

        param12 = arcpy.Parameter(
            displayName='Output Cost Table',
            name='output_tbl',
            datatype='DEFeatureClass',
            parameterType='Required',
            direction='Output'
        )

        return [param0, param1, param2, param3, param4, param5, param6,
                param7, param8, param9, param10, param11, param12]

    @staticmethod
    def updateParameters(param):
        param[1].enabled = True if param[0].value else False
        param[3].enabled = True if param[2].value else False
        if param[4].value:
            if param[12].hasBeenValidated:
                param[12].value = os.path.join(
                    os.path.dirname(param[4].valueAsText), 
                    'od_cost_output'
                )
        param[8].enabled = True if param[7].value else False
        return

    @staticmethod
    def isLicensed():
        try:
            if arcpy.CheckExtension("network") != "Available":
                raise ImportError
        except ImportError:
            return False
        return True

    @staticmethod
    def execute(param, msg):
        study_zone = param[0].valueAsText
        zone_id = param[1].valueAsText
        op_pnt = param[2].valueAsText
        op_id = param[3].valueAsText
        transit_nw_fd = param[4].valueAsText
        time_limit_total = param[5].value
        time_limit_walk = param[6].value
        res_loc = param[7].valueAsText
        res_loc_id = param[8].valueAsText
        time_of_day = param[9].value
        time_zone = param[10].valueAsText
        accum_attr = param[11].valueAsText
        output_tbl = param[12].valueAsText

        accum_attr = accum_attr.replace(" (for reference only)", "")
        accum_attr = accum_attr.replace("'", "")

        temp_ws = transit_nw_fd
        walk_coverage_lyr = 'walk_coverage'
        op_pnt_wi_walk = 'op_pnt_wi_walk'
        res_loc_zone = 'res_loc_zone'
        origins = 'origins'
        transit_od_mtx_lyr = 'transit_od_mtx'
        transit_nw_name = 'TransitNetwork_ND'
        transit_stops = 'Stops'
        stop_connectors = 'StopConnectors'
        line_variant_elements = 'LineVariantElements'

        arcpy.env.workspace = transit_nw_fd
        transit_nw = os.path.join(transit_nw_fd, transit_nw_name)
        arcpy.BuildNetwork_na(transit_nw)

        if time_limit_walk:
            msg.addMessage('Walking time limit specified. The analysis will '
                           'exclude destinations that are not reachable '
                           'within the specified limit.')
            arcpy.MakeServiceAreaAnalysisLayer_na(
                transit_nw, walk_coverage_lyr, 
                'Public transit time', 'FROM_FACILITIES', 
                time_limit_walk, '', '', 'POLYGONS',
                'STANDARD', 'DISSOLVE', 'DISKS', '100 Meters',
                f'{stop_connectors};{line_variant_elements}', 'WalkTime'
            )
            arcpy.AddLocations_na(
                walk_coverage_lyr, 'Facilities', 
                transit_stops, 'Name GStopID #', 
                '100 Meters', append='CLEAR'
            )
            msg.addMessage('Transit stops added to network.')

            arcpy.Solve_na(walk_coverage_lyr, 'SKIP', 'TERMINATE')

            op_pnt_wi_walk = os.path.join(temp_ws, op_pnt_wi_walk)
            arcpy.Clip_analysis(
                op_pnt, 
                r'{}\Polygons'.format(walk_coverage_lyr), 
                op_pnt_wi_walk
            )
            try:
                op_pnt_ct = int(arcpy.GetCount_management(op_pnt)[0])
            except TypeError:
                op_pnt_ct = 0
            if op_pnt_ct:
                msg.addMessage(f'{op_pnt_ct} destinations added to network.')
            else:
                msg.addMessage('No opportunity points (destinations) found '
                               'within the specified walking time limit. '
                               'Process terminated.')
                return

        origins = os.path.join(temp_ws, origins)
        walk_covered_arr = None

        if res_loc:
            msg.addMessage('Residential locations specified. The origins '
                           'will be shifted towards the median center of the '
                           'residential locations in each zone.')

            fm_zone_id = arcpy.FieldMap()
            fm_res_loc_id = arcpy.FieldMap()
            fms = arcpy.FieldMappings()

            fm_zone_id.addInputField(study_zone, zone_id)
            if not res_loc_id:
                res_loc_id = arcpy.ListFields(
                    res_loc, field_type='OID'
                )[0].name
            fm_res_loc_id.addInputField(res_loc, res_loc_id)

            field_zone_id = fm_zone_id.outputField
            field_zone_id.name = zone_id
            fm_zone_id.outputField = field_zone_id

            field_res_loc_id = fm_res_loc_id.outputField
            field_res_loc_id.name = res_loc_id
            fm_res_loc_id.outputField = field_res_loc_id

            fms.addFieldMap(fm_zone_id)
            fms.addFieldMap(fm_res_loc_id)

            res_loc_zone = os.path.join(temp_ws, res_loc_zone)
            arcpy.SpatialJoin_analysis(
                res_loc, study_zone, res_loc_zone, 
                'JOIN_ONE_TO_ONE', 'KEEP_COMMON', fms, 
                'HAVE_THEIR_CENTER_IN'
            )
            arcpy.CalculateField_management(
                res_loc_zone, 'WALK_COVERED', 
                0, 'PYTHON3', '', 'SHORT'
            )
            walk_res_lyr = arcpy.SelectLayerByLocation_management(
                res_loc_zone, 'HAVE_THEIR_CENTER_IN',
                r'{}\Polygons'.format(walk_coverage_lyr),
            )
            arcpy.CalculateField_management(
                walk_res_lyr, 'WALK_COVERED', 1, 'PYTHON3'
            )
            # noinspection PyUnresolvedReferences
            res_zone_arr = arcpy.da.TableToNumPyArray(
                res_loc_zone, [res_loc_id, 
                zone_id, 'WALK_COVERED']
            )
            res_zone_df = pd.DataFrame(res_zone_arr)
            res_by_zone = res_zone_df.groupby(zone_id)
            res_agg_df = res_by_zone.agg({'WALK_COVERED': 'sum',
                                          res_loc_id: 'count'})
            walk_covered_sr = (res_agg_df['WALK_COVERED'] /
                               res_agg_df[f'{res_loc_id}'])
            walk_covered_df = pd.DataFrame({
                zone_id: walk_covered_sr.index,
                'WalkCvrPct': walk_covered_sr.values
            })
            walk_covered_arr = walk_covered_df.to_records(index=False)
            arcpy.MedianCenter_stats(
                res_loc_zone, origins, '',
                zone_id, ''
            )
        else:
            arcpy.FeatureToPoint_management(study_zone, origins, 'INSIDE')

        msg.addMessage('Creating OD matrix...')
        arcpy.MakeODCostMatrixAnalysisLayer_na(
            transit_nw_name, transit_od_mtx_lyr,
            'Public transit time', time_limit_total, '',
            time_of_day, time_zone, 'NO_LINES', accum_attr
        )
        msg.addMessage('Finished creating OD matrix.')

        arcpy.AddLocations_na(
            transit_od_mtx_lyr, 
            'Origins', origins, 
            f'Name {zone_id} #', '500 Meters'
        )
        msg.addMessage('Origins added to analysis.')

        arcpy.AddLocations_na(
            transit_od_mtx_lyr, 
            'Destinations', op_pnt_wi_walk, 
            f'Name {op_id} #', '500 Meters'
        )
        msg.addMessage('Destinations added to analysis.')

        arcpy.Solve_na(transit_od_mtx_lyr, 'SKIP', 'TERMINATE')

        cost_lines = r'{}\Lines'.format(transit_od_mtx_lyr)
        zone_id_type = arcpy.ListFields(
            study_zone, wild_card=zone_id
        )[0].type

        if zone_id_type == 'String':
            id_type = 'Text'
        else:
            id_type = zone_id_type

        arcpy.CalculateField_management(
            cost_lines, 'OriginZone', 
            "!Name!.split(' - ')[0]", 
            'PYTHON3', field_type=id_type
        )

        if walk_covered_arr is not None:
            # noinspection PyUnresolvedReferences
            arcpy.da.ExtendTable(
                cost_lines, 'OriginZone',
                walk_covered_arr, zone_id
            )
        arcpy.CopyFeatures_management(cost_lines, output_tbl)
        return


class MeasureAccessibility:
    def __init__(self):
        self.label = "3. Measure Accessibility"
        self.description = ""
        self.canRunInBackground = False

    @staticmethod
    def getParameterInfo():
        param0 = arcpy.Parameter(
            displayName='Time Cost Table',
            name='time_cost_tbl',
            datatype=['GPTableView', 'GPFeatureLayer'],
            parameterType='Required',
            direction='Input'
        )

        param1 = arcpy.Parameter(
            displayName='Measuring Scale',
            name='scale',
            datatype='GPString',
            parameterType='Required',
            direction='Input'
        )
        param1.filter.list = ['Relative', 'Definite']

        param2 = arcpy.Parameter(
            displayName='Accessibility Metric',
            name='metric',
            datatype='GPString',
            parameterType='Optional',
            direction='Input'
        )
        param2.filter.list = ['Minimum Travel Time',
                              'Destination Summation',
                              'Access Score']

        param3 = arcpy.Parameter(
            displayName='Decay Function (Decay of Utility by Travel Time)',
            name='decay_func',
            datatype='GPString',
            parameterType='Optional',
            direction='Input'
        )
        param3.filter.list = ['Modified Gaussian',
                              'Negative Exponential',
                              'Negative Linear']

        param4 = arcpy.Parameter(
            displayName='Expected Opportunities\n(count per zone)',
            name='num_ops',
            datatype='GPLong',
            parameterType='Optional',
            direction='Input'
        )

        param5 = arcpy.Parameter(
            displayName='Decay Function Parameter',
            name='decay_param',
            datatype='GPDouble',
            parameterType='Optional',
            direction='Input'
        )

        param6 = arcpy.Parameter(
            displayName='Study Zones',
            name='study_zone',
            datatype='GPFeatureLayer',
            parameterType='Optional',
            direction='Input',
            category='Link Accessibility Score to Study Zones'
        )
        param6.filter.list = ['Polygon']

        param7 = arcpy.Parameter(
            displayName='Zone Unique ID',
            name='zone_id',
            datatype='Field',
            parameterType='Optional',
            direction='Input',
            category='Link Accessibility Score to Study Zones'
        )
        param7.parameterDependencies = [param6.name]

        param8 = arcpy.Parameter(
            displayName='Output',
            name='output_fc',
            datatype='DEFeatureClass',
            parameterType='Required',
            direction='Output'
        )

        param9 = arcpy.Parameter(
            displayName='Output Workspace',
            name='output_ws',
            datatype='GPString',
            parameterType='Derived',
            direction='Output'
        )

        return [param0, param1, param2, param3, param4,
                param5, param6, param7, param8, param9]

    @staticmethod
    def updateParameters(param):
        if param[0].valueAsText:
            p0_path = arcpy.Describe(param[0].valueAsText).path
            if not param[9].value:
                param[9].value = p0_path
                param[8].value = os.path.join(param[9].value,
                                              'TAA_FinalOutput')
            else:
                param[9].value = os.path.dirname(param[8].valueAsText)
                param[8].value = os.path.join(
                    param[9].value, 'TAA_FinalOutput'
                )
        param[2].enabled = True if param[1].value == 'Definite' else False
        if param[2].enabled and param[2].value == 'Access Score':
            param[3].enabled = True
            param[4].enabled = True
            param[5].enabled = True
        else:
            param[3].enabled = False
            param[4].enabled = False
            param[5].enabled = False
        if not param[3].altered:
            param[3].value = 'Modified Gaussian'
        if not param[4].altered:
            param[4].value = 3
        if not param[5].altered:
            param[5].value = 100
        return

    @staticmethod
    def execute(parameters, messages):
        od_cost_tbl = parameters[0].valueAsText
        scale = parameters[1].valueAsText
        metric = parameters[2].valueAsText
        decay_func = parameters[3].valueAsText
        num_ops = parameters[4].value
        decay_param = parameters[5].value
        study_zone = parameters[6].value
        zone_id = parameters[7].valueAsText
        output_fc = parameters[8].valueAsText

        origin_zone_id = 'OriginZone'
        cost_field = 'Total_PublicTransitTime'
        walk_cvr_pct = 'WalkCvrPct'

        # noinspection PyUnresolvedReferences
        time_cost_arr = arcpy.da.TableToNumPyArray(
            od_cost_tbl, 
            [origin_zone_id, cost_field, walk_cvr_pct]
        )
        time_cost_df = pd.DataFrame(time_cost_arr)
        cost_by_origin = time_cost_df.groupby(origin_zone_id)

        if scale == 'Relative':
            cost_df = cost_by_origin.agg({
                cost_field: 'mean', walk_cvr_pct: 'first'
            })
            cost_max = np.max(cost_df[cost_field])
            cost_min = np.min(cost_df[cost_field])
            cost_ptp = cost_max - cost_min
            # transit accessibility score
            ta_score_sr = (1 - (cost_df[cost_field] - cost_min)/cost_ptp)*100
            ta_score_sr *= cost_df[walk_cvr_pct]
            ta_score_sr.name = 'TAA_RelativeScore'
        elif scale == 'Definite':
            if metric == 'Minimum Travel Time':
                ta_score_sr = cost_by_origin[cost_field].min()
                ta_score_sr.name = 'TAA_MinTravelTime'
            elif metric == 'Destination Summation':
                ta_score_sr = cost_by_origin[cost_field].count()
                ta_score_sr.name = 'TAA_SumDestination'
            elif metric == 'Access Score':
                if decay_func == 'Gaussian':
                    time_cost_df['decay_cost'] = np.exp(
                        -time_cost_df[cost_field]**2/decay_param
                    )
                elif decay_func == 'Exponential':
                    time_cost_df['decay_cost'] = np.exp(
                        -time_cost_df[cost_field]*decay_param
                    )
                elif decay_func == 'Negative Linear':
                    time_cost_df['decay_cost'] = \
                        1 - time_cost_df[cost_field].where(
                            time_cost_df[cost_field] <= decay_param,
                            decay_param) / decay_param
                else:
                    return
                cost_decay_by_origin = time_cost_df.groupby(origin_zone_id)
                ta_score_sr = cost_decay_by_origin['decay_cost'].sum()
                ta_score_sr = np.minimum(ta_score_sr, num_ops)
                ta_score_sr = np.minimum(ta_score_sr/num_ops*100, 100)
                ta_score_sr.name = 'TAA_AccessScore'
            else:
                return
        else:
            return

        origin_zone_id_field = arcpy.ListFields(
            od_cost_tbl, 
            origin_zone_id
        )[0]

        origin_zone_id_field_type = origin_zone_id_field.type
        origin_zone_id_field_length = origin_zone_id_field.length
        ta_score_df = pd.DataFrame({
            origin_zone_id: ta_score_sr.index,
            ta_score_sr.name: ta_score_sr.values
        })
        ta_score_arr = ta_score_df.to_records(index=False)

        fc_path, fc_name = os.path.split(output_fc)

        if study_zone is not None:
            arcpy.FeatureClassToFeatureClass_conversion(
                study_zone, fc_path, fc_name
            )
            # noinspection PyUnresolvedReferences
            arcpy.da.ExtendTable(
                output_fc, zone_id, 
                ta_score_arr, origin_zone_id
            )
        else:
            if origin_zone_id_field_type == 'String':
                # "|": endian not applicable, "S": zero-terminated string
                origin_zone_id_dtype = f'|S{origin_zone_id_field_length}'
                ta_score_arr = ta_score_arr.astype(
                    dtype=[(origin_zone_id, origin_zone_id_dtype),
                           ta_score_arr.dtype.descr[1]]
                )
            # noinspection PyUnresolvedReferences
            arcpy.da.NumPyArrayToTable(ta_score_arr, output_fc)
        return


class ProposeNewRoute:
    def __init__(self):
        self.label = "4. Propose a New Route"
        self.description = ""
        self.canRunInBackground = False
        self.stops_txt = 'stops.txt'
        self.routes_txt = 'routes.txt'
        self.trips_txt = 'trips.txt'
        self.calendar_txt = 'calendar.txt'
        self.stop_times_txt = 'stop_times.txt'
        self.route_color = '7FFF00'

    @staticmethod
    def getParameterInfo():
        param0 = arcpy.Parameter(
            displayName='Input GTFS Folder',
            name='input_gtfs',
            datatype='DEFolder',
            parameterType='Required',
            direction='Input'
        )

        param1 = arcpy.Parameter(
            displayName='gtfs folder',
            name='gtfs_folder',
            datatype='GPString',
            parameterType='Derived',
            direction='Output'
        )
        param1.value = ''

        param2 = arcpy.Parameter(
            displayName='Proposed Stops',
            name='stop_fc',
            datatype='GPFeatureLayer',
            parameterType='Required',
            direction='Input'
        )
        param2.filter.list = ['Point']

        param3 = arcpy.Parameter(
            displayName='Proposed Route ID',
            name='route_id',
            datatype='GPLong',
            parameterType='Required',
            direction='Input'
        )

        param4 = arcpy.Parameter(
            displayName='Proposed Services',
            name='services',
            datatype='GPValueTable',
            parameterType='Required',
            direction='Input'
        )
        param4.columns = [['GPString', 'Service ID'],
                          ['GPLong', 'Number of Trips']]

        param5 = arcpy.Parameter(
            displayName='route id list',
            name='route_id_list',
            datatype='GPString',
            parameterType='Derived',
            direction='Output'
        )

        param6 = arcpy.Parameter(
            displayName='service id list',
            name='services_id_list',
            datatype='GPString',
            parameterType='Derived',
            direction='Output'
        )

        param7 = arcpy.Parameter(
            displayName='First Trip Start at',
            name='start_time',
            datatype='GPDate',
            parameterType='Required',
            direction='Input'
        )
        param7.value = '08:00:00'

        param8 = arcpy.Parameter(
            displayName='Average Time Cost (minutes/trip)',
            name='minutes_per_trip',
            datatype='GPTimeUnit',
            parameterType='Required',
            direction='Input'
        )
        param8.filter.list = ['Minutes']

        param9 = arcpy.Parameter(
            displayName='Output GTFS Folder',
            name='output_gtfs',
            datatype='DEFolder',
            parameterType='Required',
            direction='Output'
        )

        param10 = arcpy.Parameter(
            displayName='Stop Name',
            name='stop_name',
            datatype='Field',
            parameterType='Optional',
            direction='Input',
            category='Additional Stops Setting'
        )
        param10.parameterDependencies = [param2.name]

        param11 = arcpy.Parameter(
            displayName='Stop Description',
            name='stop_desc',
            datatype='Field',
            parameterType='Optional',
            direction='Input',
            category='Additional Stops Setting'
        )
        param11.parameterDependencies = [param2.name]

        param12 = arcpy.Parameter(
            displayName='Wheelchair Boarding',
            name='stop_wc_brd',
            datatype='Field',
            parameterType='Optional',
            direction='Input',
            category='Additional Stops Setting'
        )
        param12.parameterDependencies = [param2.name]

        param13 = arcpy.Parameter(
            displayName='Route Name',
            name='route_name',
            datatype='GPString',
            parameterType='Optional',
            direction='Input',
            category='Additional Route Setting'
        )

        param14 = arcpy.Parameter(
            displayName='Route Type',
            name='route_type',
            datatype='GPString',
            parameterType='Optional',
            direction='Input',
            category='Additional Route Setting'
        )
        param14.filter.list = ['Tram, Streetcar, Light rail',
                               'Subway, Metro',
                               'Rail',
                               'Bus']
        param14.value = param14.filter.list[3]

        return [param0, param1, param2, param3, param4,
                param5, param6, param7, param8, param9,
                param10, param11, param12, param13, param14]

    def updateParameters(self, param):
        if param[0].valueAsText:
            if param[1].valueAsText != param[0].valueAsText:
                routes_df = pd.read_csv(
                    os.path.join(param[0].valueAsText,
                                 self.routes_txt)
                )
                param[5].value = str(list(routes_df['route_id'].unique()))
                calendar_df = pd.read_csv(
                    os.path.join(param[0].valueAsText,
                                 self.calendar_txt)
                )
                param[6].value = str(list(calendar_df['service_id'].unique()))
                param[1].value = param[0].valueAsText
            if param[9].hasBeenValidated:
                param[9].value = param[0].valueAsText + '_new_route'
        if param[6].value:
            service_id_list = ast.literal_eval(param[6].value)
            param[4].filters[0].type = 'ValueList'
            param[4].filters[0].list = service_id_list
        return

    def updateMessages(self, param):
        if param[5].value:
            route_id_list = ast.literal_eval(param[5].value)
            if param[3].value in route_id_list:
                param[3].setErrorMessage(f'Route "{param[3].value}" already '
                                         f'exists. Try a different route id.')
        if param[8].value:
            if float(param[8].valueAsText.split()[0]) <= 0:
                param[8].setErrorMessage('Must input a positive value.')

    def execute(self, param, msg):
        input_gtfs = param[0].valueAsText
        stop_fc = param[2].valueAsText
        route_id = param[3].value
        services = param[4].value
        start_time = param[7].valueAsText
        minutes_per_trip = param[8].valueAsText
        output_gtfs = param[9].valueAsText
        stop_name = param[10].valueAsText
        stop_desc = param[11].valueAsText
        stop_wc_brd = param[12].valueAsText
        route_name = param[13].valueAsText
        route_type = param[14].valueAsText

        shutil.copytree(input_gtfs, output_gtfs)
        stops_txt = os.path.join(output_gtfs, self.stops_txt)
        stop_df_old = pd.read_csv(stops_txt)
        stop_id_old_max = stop_df_old['stop_id'].max()

        stop_field = ['SHAPE@XY']
        [stop_field.append(f)
         for f in [stop_name, stop_desc, stop_wc_brd] if f]

        # noinspection PyUnresolvedReferences
        stop_arr = arcpy.da.FeatureClassToNumPyArray(
            stop_fc, stop_field,
            spatial_reference=arcpy.SpatialReference(4326)
        )
        stop_id_new = np.arange(len(stop_arr)) + stop_id_old_max + 1

        if not stop_name:
            stop_name = stop_id_new.astype('str')
        else:
            stop_name = stop_arr[stop_name]
        if not stop_desc:
            stop_desc = stop_id_new.astype('str')
        else:
            stop_desc = stop_arr[stop_desc]
        if not stop_wc_brd:
            stop_wc_brd = np.empty(len(stop_arr), dtype='str')
        else:
            stop_wc_brd = stop_arr[stop_wc_brd]

        stop_df_new = pd.DataFrame(
            np.column_stack((stop_id_new, stop_id_new,
                             stop_name, stop_desc,
                             stop_arr['SHAPE@XY'][:, 1],
                             stop_arr['SHAPE@XY'][:, 0],
                             np.zeros(len(stop_arr),
                                      dtype=np.int8),
                             stop_wc_brd)),
            columns=['stop_id', 'stop_code',
                     'stop_name', 'stop_desc',
                     'stop_lat', 'stop_lon',
                     'location_type',
                     'wheelchair_boarding']
        )

        stop_result = stop_df_old.append(stop_df_new, ignore_index=True)
        stop_result.to_csv(stops_txt, index=False)

        route_txt = os.path.join(output_gtfs, self.routes_txt)
        route_df_old = pd.read_csv(route_txt)
        if not route_name:
            route_name = str(route_id)
        route_type_dict = {'Tram, Streetcar, Light rail': '0',
                           'Subway, Metro': '1',
                           'Rail': '2',
                           'Bus': '3'}
        route_type = route_type_dict[route_type]  # 3 - Bus (by default).
        # Used for short- and long-distance bus routes. See
        # https://developers.google.com/transit/gtfs/reference#routestxt.
        route_df_new = pd.DataFrame(
            np.column_stack((route_id, str(route_id),
                             route_name, self.route_color,
                             route_type)),
            columns=['route_id', 'route_short_name',
                     'route_long_name', 'route_color',
                     'route_type']
        )
        route_result = route_df_old.append(route_df_new, ignore_index=True)
        route_result.to_csv(route_txt, index=False)

        trips_txt = os.path.join(output_gtfs, self.trips_txt)
        trips_df = pd.read_csv(trips_txt)
        stop_times_txt = os.path.join(output_gtfs, self.stop_times_txt)
        stop_times_df = pd.read_csv(stop_times_txt)

        stops_d1 = stop_id_new[:len(stop_id_new)//2]
        stops_d2 = stop_id_new[len(stop_id_new)//2:]

        for service in services:
            service_id, num_trips = service
            max_trip_id = np.max(trips_df['trip_id'])
            trip_ids = np.arange(num_trips*2) + max_trip_id + 1
            trip_ids_d1 = trip_ids[::2]
            trip_ids_d2 = trip_ids[1::2]
            trip_ids_dict = {1: trip_ids_d1, 2: trip_ids_d2}
            trip_funcs_dict = {1: np.ones, 2: np.zeros}

            for key in trip_ids_dict.keys():
                new_trips_df = pd.DataFrame(
                    np.column_stack((trip_ids_dict[key],
                                     np.full(num_trips, route_id),
                                     np.full(num_trips, service_id),
                                     trip_funcs_dict[key](num_trips))),
                    columns=['trip_id', 'route_id',
                             'service_id', 'direction_id']
                )
                trips_df = trips_df.append(new_trips_df, ignore_index=True)
            trips_df.to_csv(trips_txt, index=False)

            stops_dict = {1: stops_d1, 2: stops_d2}

            for key in trip_ids_dict.keys():
                try:
                    dt_start_time = dt.datetime.strptime(
                        start_time, '%I:%M:%S %p'
                    ).time()
                except ValueError:
                    try:
                        dt_start_time = dt.datetime.strptime(
                            start_time, '%m/%d/%Y %I:%M:%S %p'
                        ).time()
                    except ValueError:
                        msg.AddMessage(f'Invalid start time {start_time}.')
                        raise ValueError('Program stopped.')
                dt_start_datetime = dt.datetime.combine(
                    dt.datetime.today(), dt_start_time
                )
                dt_minutes_per_trip = dt.timedelta(
                    minutes=float(minutes_per_trip.split()[0])
                )

                for trip_id in trip_ids_dict[key]:
                    arrival_times = np.empty(len(stops_dict[key]), dtype='<U8')
                    if key == 1:
                        arrival_times[0] = str(dt_start_datetime.time())
                        arrival_times[-1] = str(
                            (dt_start_datetime + dt_minutes_per_trip).time()
                        )
                    else:
                        arrival_times[0] = str(
                            (dt_start_datetime + dt_minutes_per_trip).time()
                        )
                        arrival_times[-1] = str(
                            (dt_start_datetime + 2*dt_minutes_per_trip).time()
                        )
                    arrival_times[1:-1] = ''
                    departure_times = arrival_times
                    timepoint = np.zeros(len(stops_dict[key]))
                    timepoint[0] = timepoint[-1] = 1
                    new_stop_times_df = pd.DataFrame(
                        np.column_stack((np.full(len(stops_dict[key]),
                                                 trip_id),
                                         arrival_times, departure_times,
                                         stops_d1,
                                         np.arange(len(stops_dict[key])),
                                         timepoint)),
                        columns=['trip_id',
                                 'arrival_time', 'departure_time',
                                 'stop_id', 'stop_sequence',
                                 'timepoint']
                    )
                    dt_start_datetime = (dt_start_datetime +
                                         2*dt_minutes_per_trip)
                    stop_times_df = stop_times_df.append(
                        new_stop_times_df, ignore_index=True
                    )
                                                         
            stop_times_df.to_csv(stop_times_txt, index=False)
        return
