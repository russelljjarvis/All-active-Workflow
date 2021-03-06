import os
from allensdk.core.nwb_data_set import NwbDataSet
from ipfx.aibs_data_set import AibsDataSet
from ipfx.stim_features import get_stim_characteristics
import ipfx.bin.lims_queries as lq
import numpy as np
import json
from collections import defaultdict
import efel
import math
from ateamopt.utils import utility
from ateamopt.optim_config_rules import correct_voltage_feat_std
import logging
import itertools

logger = logging.getLogger(__name__)


class NwbExtractor(object):

    def __init__(self, cell_id, nwb_path, junc_potential=-14, temp=34):

        self.cell_id = cell_id
        self.junction_potential = junc_potential
        self.temperature = temp

        self._nwb_path = nwb_path

    @property
    def nwb_path(self):
        return self._nwb_path

    @staticmethod
    def calc_stimparams(time, stimulus_trace, trace_name):
        """Calculate stimuls start, stop and amplitude from trace"""

        nonzero_indices = np.where(stimulus_trace != 0)[0]

        # make sure if the stimulus is ok if there was no input
        # if the stimulus is zero
        if not nonzero_indices.any():   # if the list is empty
            # arbitrary values for the no-stimulus response
            stim_start = time[20000]    # after 100ms
            stim_stop = time[-1]        # until the end
            stim_amp_start = 0
            stim_amp_end = 0
            hold_curr = 0
        else:
            # if the stimulus is not zero
            stim_start = time[nonzero_indices[0]]
            stim_stop = time[nonzero_indices[-1]]
            if 'DC' in trace_name:
                hold_curr = np.mean(stimulus_trace[nonzero_indices[-1]+1000:
                                                   nonzero_indices[-1] + 20000])*1e12
            else:
                hold_curr = 0

            if np.isnan(hold_curr):
                hold_curr = 0
            stim_amp_start = stimulus_trace[nonzero_indices[0]] * 1e12 - hold_curr
            stim_amp_end = stimulus_trace[nonzero_indices[-1]] * 1e12 - hold_curr

        tot_duration = time[-1]
        return stim_start, stim_stop, stim_amp_start, stim_amp_end, tot_duration, hold_curr

    @staticmethod
    def calc_stimparams_ipfx(time, stimulus_trace, trace_name):
        start_time, duration, amplitude, start_idx, end_idx = get_stim_characteristics(
            stimulus_trace, time)
        amplitude *= 1e12
        stim_stop = start_time + duration
        stim_amp_start = 1e12 * stimulus_trace[start_idx]
        stim_amp_end = amplitude
        tot_duration = min(time[-1], stim_stop+1.0)  # 1sec beyond stim end
        hold_curr = 0.0
        return start_time, stim_stop, stim_amp_start, stim_amp_end, tot_duration, hold_curr

    @staticmethod
    def calc_stimparams_nonstandard(time, stimulus_trace, trace_name):
        """Calculate stimuls start, stop and amplitude from trace for nonstandard nwb"""

        # if the stimulus is not empty
        # find the max/min of the noisy signal
        gradient_thresh = 10  # arbitrary
        gradient_f = np.gradient(stimulus_trace)*1e12
        gradient_f[abs(gradient_f) <= gradient_thresh] = 0

        nonzero_indices = np.where(gradient_f != 0)[0]

        if not nonzero_indices.any():

            stim_start = time[20000]    # after 100ms (arbitrary)
            stim_stop = time[40000]     # after 200ms (arbitrary)
            stim_amp_start = 0.0
            stim_amp_end = 0.0
            hold_curr = np.mean(stimulus_trace[-20000:])*1e12

        else:

            signal_max = max(gradient_f)
            signal_min = min(gradient_f)

            # find the max/min of the gradient
            first_ind = np.where(gradient_f == signal_max)[0][0]
            second_ind = np.where(gradient_f == signal_min)[0][0]

            # check for the first and second indexes
            if first_ind > second_ind:
                start_ind = second_ind
                end_ind = first_ind
            elif first_ind < second_ind:
                start_ind = first_ind
                end_ind = second_ind

            stim_start = time[start_ind]
            stim_stop = time[end_ind]

            # check for the middle part of the signal

            # approximate the amp, it is the mean between the start and end
            if 'DC' in trace_name:
                hold_curr = np.mean(
                    stimulus_trace[end_ind+1000:end_ind + 20000])*1e12
            else:
                hold_curr = 0

            if np.isnan(hold_curr):
                hold_curr = 0
            stim_amp = np.mean(
                stimulus_trace[start_ind:end_ind]) * 1e12 - hold_curr
            stim_amp_start = stim_amp
            stim_amp_end = stim_amp
        tot_duration = time[-1]

        return stim_start, stim_stop, stim_amp_start, stim_amp_end, tot_duration, hold_curr

    @staticmethod
    def write_stimmap_csv(stim_map, output_dir, stim_sweep_map):
        """Write StimMap.csv"""

        stim_reps_sweep_map = {}

        stimmapreps_csv_content = "DistinctID, StimType, HoldingCurrent, "\
            "Amplitude_Start, Amplitude_End, Stim_Start, Stim_End, Duration, DataPath\n"

        reps = defaultdict(lambda: defaultdict(list))
        for stim_type in stim_map:
            for trace_params in stim_map[stim_type]:

                amplitude = str(trace_params[3])+'&' + str(trace_params[6])
                reps[stim_type][amplitude].append(trace_params)

        for stim_type in reps:
            for amplitude in reps[stim_type]:

                cumul_params = reps[stim_type][amplitude][0]

                trace_name = cumul_params[0]

                cumul_params[2] = np.mean(
                    [rep_params[2] for rep_params in reps
                     [stim_type][amplitude]])

                cumul_params[8] = "|".join(
                    rep_params[8] for rep_params in reps[stim_type][amplitude])

                rep_names = [rep_params[0]
                             for rep_params in reps[stim_type][amplitude]]
                rep_sweeps = [stim_sweep_map[rep_name]
                              for rep_name in rep_names]
                stim_reps_sweep_map[trace_name] = rep_sweeps

                tstart_set = set(['%.1f' % rep_params[5]
                                  for rep_params in reps[stim_type][amplitude]])
                if len(tstart_set) != 1:
                    raise Exception(
                        "Stim type %s Amplitude %s don't have equal start "
                        "times: %s" %
                        (stim_type, amplitude.split('&')[0], str(tstart_set)))

                tstop_set = set(['%.1f' % rep_params[6]
                                 for rep_params in reps[stim_type][amplitude]])
                if len(tstop_set) != 1:
                    raise Exception(
                        "Stim type %s Amplitude %s don't have equal stop "
                        "times: %s" %
                        (stim_type, amplitude.split('&')[0], str(tstop_set)))

                stimmapreps_csv_content += ",".join([str(x)
                                                     for x in cumul_params])
                stimmapreps_csv_content += '\n'

        stimmap_filename = 'StimMapReps.csv'
        stimmapreps_csv_filename = os.path.join(output_dir, stimmap_filename)

        with open(stimmapreps_csv_filename, 'w') as stimmapreps_csv_file:
            stimmapreps_csv_file.write(stimmapreps_csv_content)

        return stim_reps_sweep_map, stimmapreps_csv_filename

    @staticmethod
    def calculate_md5hash(filename):
        """Calculate the md5hash of a file"""

        import hashlib
        with open(filename, 'rb') as file_h:
            md5hash = hashlib.md5(file_h.read()).hexdigest()

        return md5hash

    def write_provenance(self,
                         output_dir,
                         nwb_filename,
                         stim_sweep_map,
                         stim_reps_sweep_map):
        """Writing provenance file"""

        provenance_filename = os.path.join(output_dir, 'provenance.json')

        nwb_md5hash = self.calculate_md5hash(nwb_filename)

        provenance = {
            'nwb_filename': os.path.abspath(nwb_filename),
            'nwb_md5hash': nwb_md5hash,
            'temperature': self.temperature,
            'junction_potential': self.junction_potential,
            'stim_sweep_map': stim_sweep_map,
            'stim_reps_sweep_map': stim_reps_sweep_map}

        with open(provenance_filename, 'w') as provenance_file:
            json.dump(
                provenance,
                provenance_file,
                sort_keys=True,
                indent=4,
                separators=(
                    ',',
                    ': '))

    def save_cell_data_web(self, acceptable_stimtypes, non_standard_nwb=False,
                           ephys_dir='preprocessed', **kwargs):

        bpopt_stimtype_map = utility.bpopt_stimtype_map
        distinct_id_map = utility.aibs_stimname_map
        nwb_file = NwbDataSet(self.nwb_path)

        stim_map = defaultdict(list)
        stim_sweep_map = {}
        output_dir = os.path.join(os.getcwd(), ephys_dir)
        utility.create_dirpath(output_dir)

        sweep_numbers = kwargs.get('sweep_numbers') or nwb_file.get_sweep_numbers()
        for sweep_number in sweep_numbers:
            sweep_data = nwb_file.get_sweep_metadata(sweep_number)
            stim_type = sweep_data['aibs_stimulus_name']

            try:
                stim_type = stim_type.decode('UTF-8')
            except:
                pass

            if stim_type in acceptable_stimtypes:
                sweep = nwb_file.get_sweep(sweep_number)

                start_idx, stop_idx = sweep['index_range']

                stimulus_trace = sweep['stimulus'][start_idx:stop_idx]
                response_trace = sweep['response'][start_idx:stop_idx]

                sampling_rate = sweep['sampling_rate']

                time = np.arange(0, len(stimulus_trace)) / sampling_rate
                trace_name = '%s_%d' % (
                    distinct_id_map[stim_type], sweep_number)

                if non_standard_nwb:
                    calc_stimparams_func = self.calc_stimparams_nonstandard
                else:
                    calc_stimparams_func = self.calc_stimparams

                stim_start, stim_stop, stim_amp_start, stim_amp_end, \
                    tot_duration, hold_curr = calc_stimparams_func(
                        time, stimulus_trace, trace_name)

                response_trace_short_filename = '%s.%s' % (trace_name, 'txt')
                response_trace_filename = os.path.join(
                    output_dir, response_trace_short_filename)

                time *= 1e3  # in ms
                response_trace *= 1e3  # in mV
                response_trace = utility.correct_junction_potential(response_trace,
                                                                    self.junction_potential)
                stimulus_trace *= 1e9

                # downsampling
                time, stimulus_trace, response_trace = utility.downsample_ephys_data(
                    time, stimulus_trace, response_trace)

                if stim_type in utility.bpopt_current_play_stimtypes:
                    with open(response_trace_filename, 'wb') as response_trace_file:
                        np.savetxt(response_trace_file,
                                   np.transpose([time, response_trace, stimulus_trace]))

                else:
                    with open(response_trace_filename, 'wb') as response_trace_file:
                        np.savetxt(response_trace_file,
                                   np.transpose([time, response_trace]))

                holding_current = hold_curr  # sweep['bias_current']

                stim_map[distinct_id_map[stim_type]].append([
                    trace_name,
                    bpopt_stimtype_map[stim_type],
                    holding_current/1e12,
                    stim_amp_start / 1e12,
                    stim_amp_end/1e12,
                    stim_start * 1e3,
                    stim_stop * 1e3,
                    tot_duration * 1e3,
                    response_trace_short_filename])

                stim_sweep_map[trace_name] = sweep_number

        logger.debug('Writing stimmap.csv ...')
        stim_reps_sweep_map, stimmap_filename = self.write_stimmap_csv(stim_map,
                                                                       output_dir, stim_sweep_map)

        self.write_provenance(
            output_dir,
            self.nwb_path,
            stim_sweep_map,
            stim_reps_sweep_map)

        return output_dir, stimmap_filename

    def save_cell_data(self, acceptable_stimtypes, non_standard_nwb=False,
                       ephys_dir='preprocessed'):

        bpopt_stimtype_map = utility.bpopt_stimtype_map
        distinct_id_map = utility.aibs_stimname_map
        # Note: may also need to provide h5 "lab notebok" and/or ontology
        from ipfx.stimulus import StimulusOntology
        from ipfx.epochs import get_recording_epoch
        import allensdk.core.json_utilities as ju
        ontology = StimulusOntology(
            ju.read(StimulusOntology.DEFAULT_STIMULUS_ONTOLOGY_FILE))
        dataset = AibsDataSet(nwb_file=self.nwb_path, ontology=ontology)

        stim_map = defaultdict(list)
        stim_sweep_map = {}
        output_dir = os.path.join(os.getcwd(), ephys_dir)
        utility.create_dirpath(output_dir)

        # Note: are QC criteria appropriate for ramps + other stim?
        passed_sweep_nums = get_passed_sweeps(dataset, self.cell_id)
        for sweep_num in passed_sweep_nums:
            record = dataset.get_sweep_record(sweep_num)
            sweep_number = record[AibsDataSet.SWEEP_NUMBER]
            stim_type = record[AibsDataSet.STIMULUS_NAME]

            if stim_type in acceptable_stimtypes:
                # TODO: use dataset.sweep to get full object, epochs
                sweep = dataset.get_sweep_data(sweep_number)

                stimulus_trace = sweep['stimulus']
                response_trace = sweep['response']
                sampling_rate = sweep['sampling_rate']

                # remove missing data
                # start, end = get_recording_epoch(stimulus_trace)
                # stimulus_trace = stimulus_trace[:end]
                # response_trace = response_trace[:end]
                time = np.arange(0, len(stimulus_trace)) / sampling_rate

                trace_name = '%s_%d' % (
                    distinct_id_map[stim_type], sweep_number)

                if non_standard_nwb:
                    calc_stimparams_func = self.calc_stimparams_nonstandard
                else:
                    calc_stimparams_func = self.calc_stimparams_ipfx

                stim_start, stim_stop, stim_amp_start, stim_amp_end, \
                    tot_duration, hold_curr = calc_stimparams_func(
                        time, stimulus_trace, trace_name)

                response_trace_short_filename = '%s.%s' % (trace_name, 'txt')
                response_trace_filename = os.path.join(
                    output_dir, response_trace_short_filename)

                time *= 1e3  # in ms
                response_trace *= 1e3  # in mV
                response_trace = utility.correct_junction_potential(response_trace,
                                                                    self.junction_potential)
                stimulus_trace *= 1e9

                # downsampling
                time, stimulus_trace, response_trace = utility.downsample_ephys_data(
                    time, stimulus_trace, response_trace)

                # save current timeseries only when needed
                if stim_type in utility.bpopt_current_play_stimtypes:
                    with open(response_trace_filename, 'wb') as response_trace_file:
                        np.savetxt(response_trace_file,
                                   np.transpose([time, response_trace, stimulus_trace]))

                else:
                    with open(response_trace_filename, 'wb') as response_trace_file:
                        np.savetxt(response_trace_file,
                                   np.transpose([time, response_trace]))

                stim_map[distinct_id_map[stim_type]].append([
                    trace_name,
                    bpopt_stimtype_map[stim_type],
                    hold_curr / 1e12,
                    stim_amp_start / 1e12,
                    stim_amp_end / 1e12,
                    stim_start * 1e3,
                    stim_stop * 1e3,
                    tot_duration * 1e3,
                    response_trace_short_filename])

                stim_sweep_map[trace_name] = sweep_number

        logger.debug('Writing stimmap.csv ...')
        stim_reps_sweep_map, stimmap_filename = self.write_stimmap_csv(stim_map,
                                                                       output_dir, stim_sweep_map)

        self.write_provenance(
            output_dir,
            self.nwb_path,
            stim_sweep_map,
            stim_reps_sweep_map)

        return output_dir, stimmap_filename

    @staticmethod
    def get_stim_map(stim_map_filename, record_locations=None):
        """Get stim map"""

        stim_map = defaultdict(dict)

        with open(stim_map_filename, 'r') as stim_map_file:
            stim_map_content = stim_map_file.read()

        for line in stim_map_content.split('\n')[1:-1]:
            if line != '':
                stim_name, stim_type, holding_current, amplitude_start, amplitude_end, \
                    stim_start, stim_end, duration, sweeps = line.split(',')
                iter_dict1, iter_dict2 = dict(), dict()
                iter_dict1['type'] = stim_type.strip()
                iter_dict1['amp'] = 1e9 * float(amplitude_start)
                iter_dict1['amp_end'] = 1e9 * float(amplitude_end)
                iter_dict1['delay'] = float(stim_start)
                iter_dict1['duration'] = float(stim_end) - float(stim_start)
                iter_dict1['stim_end'] = float(stim_end)
                iter_dict1['totduration'] = float(duration)
                iter_dict1['sweep_filenames'] = [
                    x.strip() for x in sweeps.split('|')]

                if 'Ramp' in stim_name:
                    holding_current = 0
                iter_dict2['type'] = 'SquarePulse'
                iter_dict2['amp'] = 1e9 * float(holding_current)
                iter_dict2['amp_end'] = 1e9 * float(holding_current)
                iter_dict2['delay'] = 0
                iter_dict2['duration'] = float(duration)
                iter_dict2['stim_end'] = float(duration)
                iter_dict2['totduration'] = float(duration)

                if float(holding_current) != 0.0:
                    iter_list = [iter_dict1, iter_dict2]
                else:
                    iter_list = [iter_dict1]

                stim_map[stim_name]['stimuli'] = iter_list
                if record_locations:
                    record_list = list()
                    for i, loc in enumerate(record_locations):
                        record_dict = dict()
                        record_dict['var'] = 'v'
                        record_dict['somadistance'] = loc
                        record_dict["seclist_name"] = "apical"
                        record_dict['name'] = 'dend' + str(i+1)
                        record_dict['type'] = 'somadistance'
                        record_list.append(record_dict)
                    stim_map[stim_name]['extra_recordings'] = record_list
        return stim_map

    def get_efeatures_all(self, feature_set_filename, ephys_data_path, stimmap_filename,
                          *args, **kwargs):
        cell_name = self.cell_id

        feature_map = utility.load_json(feature_set_filename)

        features_meanstd = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(dict)))
        stim_map = self.get_stim_map(
            os.path.join(ephys_data_path, stimmap_filename))
        for stim_name in stim_map.keys():
            stim_type = utility.aibs_stimname_map_inv[stim_name.rsplit('_', 1)[0]]
            stim_features = feature_map.get(stim_type)  # Features to extract
            if not stim_features:
                continue
            logger.debug("\n### Getting features from %s of cell %s ###\n"
                         % (stim_name, cell_name))

            sweeps = []
            for sweep_filename in stim_map[stim_name]['stimuli'][0]['sweep_filenames']:
                sweep_fullpath = os.path.join(
                    ephys_data_path,
                    sweep_filename)

                data = np.loadtxt(sweep_fullpath)
                tot_duration = stim_map[stim_name]['stimuli'][0]['totduration']
                time, voltage = data[:, 0], data[:, 1]

                # Limit the duration of stim for correct stim end feature calculation
                time, voltage = time[time <= tot_duration], voltage[time <= tot_duration]

                # Prepare sweep for eFEL
                sweep = {}
                sweep['T'] = time
                sweep['V'] = voltage
                sweep['stim_start'] = [
                    stim_map[stim_name]['stimuli'][0]['delay']]
                sweep['stim_end'] = [
                    stim_map[stim_name]['stimuli'][0]['stim_end']]

                if 'check_AISInitiation' in stim_features:
                    sweep['T;location_AIS'] = time
                    sweep['V;location_AIS'] = voltage
                    sweep['stim_start;location_AIS'] = [
                        stim_map[stim_name]['stimuli'][0]['delay']]
                    sweep['stim_end;location_AIS'] = [
                        stim_map[stim_name]['stimuli'][0]['stim_end']]
                sweeps.append(sweep)

            # eFEL feature extraction
            feature_results = efel.getFeatureValues(sweeps, stim_features)

            for feature_name in stim_features:
                # For one feature, a list with values for every sweep
                feature_values_over_trials = [trace_dict[feature_name].tolist() for trace_dict
                                              in feature_results if trace_dict[feature_name] is not None]
                feature_mean_over_trials = [np.nanmean(trace_dict[feature_name])
                                            for trace_dict in feature_results
                                            if trace_dict[feature_name] is not None]
                if len(feature_mean_over_trials) == 0:
                    continue
                else:
                    mean = np.nanmean(
                        list(itertools.chain.from_iterable(feature_values_over_trials)))
                    std = (np.nanstd(list(itertools.chain.from_iterable(feature_values_over_trials))) or
                           0.05*np.abs(mean) or 0.05)

                if feature_name == 'peak_time':
                    mean, std = None, None

                features_meanstd[stim_name]['soma'][
                    feature_name] = [mean, std, feature_values_over_trials]

        return stim_map, features_meanstd

    def get_ephys_features(self, feature_set_filename, ephys_data_path, stimmap_filename,
                           filter_rule_func, *args, **kwargs):
        cell_name = self.cell_id

        feature_map = utility.load_json(feature_set_filename)
        stim_features = feature_map['features']  # Features to extract

        features_meanstd = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(dict)))
        features_meanstd_lite = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(dict)))
        # if additional dendritic recordings
        if 'location' in kwargs:
            record_locations = kwargs['locations']
        else:
            record_locations = None

        stim_map = self.get_stim_map(os.path.join(ephys_data_path, stimmap_filename),
                                     record_locations=record_locations)

        cell_stim_map = stim_map.copy()
        training_stim_map = dict()
        spiketimes_noise = defaultdict(list)

        for stim_name in stim_map.keys():
            if 'feature_reject_stim_type' in kwargs:
                if any(reject_feat_stim in stim_name for reject_feat_stim in
                       kwargs['feature_reject_stim_type']):
                    continue

            logger.debug("\n### Getting features from %s of cell %s ###\n"
                         % (stim_name, cell_name))

            sweeps = []
            for sweep_filename in stim_map[stim_name]['stimuli'][0]['sweep_filenames']:
                sweep_fullpath = os.path.join(
                    ephys_data_path,
                    sweep_filename)

                data = np.loadtxt(sweep_fullpath)
                time = data[:, 0]
                voltage = data[:, 1]

                # Prepare sweep for eFEL
                sweep = {}
                sweep['T'] = time
                sweep['V'] = voltage
                sweep['stim_start'] = [
                    stim_map[stim_name]['stimuli'][0]['delay']]
                sweep['stim_end'] = [
                    stim_map[stim_name]['stimuli'][0]['stim_end']]
                sweep['T;location_AIS'] = time
                sweep['V;location_AIS'] = voltage
                sweep['stim_start;location_AIS'] = [
                    stim_map[stim_name]['stimuli'][0]['delay']]
                sweep['stim_end;location_AIS'] = [
                    stim_map[stim_name]['stimuli'][0]['stim_end']]
                sweeps.append(sweep)

            if 'Noise' in stim_name:
                feature_results = efel.getFeatureValues(sweeps, ['peak_time'])
                for feature_result in feature_results:
                    spiketimes_noise[stim_name].append(
                        feature_result['peak_time'])
                continue

            # eFEL feature extraction
            feature_results = efel.getFeatureValues(sweeps, stim_features)

            for feature_name in stim_features:
                # For one feature, a list with values for every sweep
                feature_values = [np.mean(trace_dict[feature_name])
                                  for trace_dict in feature_results
                                  if trace_dict[feature_name] is not None]
                if len(feature_values) == 0:
                    continue
                elif len(feature_values) == 1:
                    mean = feature_values[0]
                    std = 0.05 * abs(mean)
                elif len(feature_values) > 1:
                    mean = np.mean(feature_values)
                    std = np.std(feature_values)

                if std == 0 and len(feature_values) != 1:
                    std = 0.05 * abs(mean)/math.sqrt(len(feature_values))

                if math.isnan(mean) or math.isnan(std):
                    continue
                if mean == 0:
                    std = 0.05

                if feature_name in ['voltage_base', 'steady_state_voltage'] \
                        and len(feature_values) == 1:
                    std = 0

                features_meanstd[stim_name]['soma'][
                    feature_name] = [mean, std]

                # Remove depolarization block and check initiation from all features list
                if feature_name not in ['depol_block', 'check_AISInitiation']:
                    features_meanstd_lite[stim_name]['soma'][
                        feature_name] = [mean, std]
            if stim_name in features_meanstd.keys():
                training_stim_map[stim_name] = cell_stim_map[stim_name]

        if kwargs.get('spiketimes_exp_path'):
            spiketimes_exp_path = kwargs['spiketimes_exp_path']
            if len(spiketimes_noise.keys()) > 0:
                utility.create_filepath(spiketimes_exp_path)
                utility.save_pickle(spiketimes_exp_path, spiketimes_noise)

        features_meanstd_filtered, untrained_features_dict, training_stim_map_filtered,\
            all_stim_filtered = filter_rule_func(features_meanstd.copy(), training_stim_map,
                                                 cell_stim_map, *args)
        features_meanstd_lite = correct_voltage_feat_std(features_meanstd_lite)

        return features_meanstd_filtered, untrained_features_dict,\
            features_meanstd_lite, training_stim_map_filtered,\
            all_stim_filtered

    def write_ephys_features(self, train_features, test_features,
                             train_protocols, base_dir='config/', **kwargs):
        cell_name = self.cell_id
        train_features_write_path = kwargs.get('train_features_write_path') or \
            os.path.join(base_dir, cell_name, 'train_features.json')
        test_features_write_path = kwargs.get('test_features_write_path') \
            or os.path.join(base_dir, cell_name, 'test_features.json')
        train_protocols_write_path = kwargs.get('protocols_write_path') \
            or os.path.join(base_dir, cell_name, 'train_protocols.json')
        utility.create_filepath(train_protocols_write_path)
        utility.save_json(train_features_write_path, train_features)
        utility.save_json(test_features_write_path, test_features)
        utility.save_json(train_protocols_write_path, train_protocols)

        return train_features_write_path, test_features_write_path,\
            train_protocols_write_path


def get_passed_sweeps(dataset, specimen_id):
    iclamp_st = dataset.filtered_sweep_table(clamp_mode=AibsDataSet.CURRENT_CLAMP)
    exist_sql = """
        select swp.sweep_number from ephys_sweeps swp
        where swp.specimen_id = :1
        and swp.sweep_number = any(:2)
    """
    passed_sql = """
    select swp.sweep_number from ephys_sweeps swp
    where swp.specimen_id = :1
    and swp.sweep_number = any(:2)
    and swp.workflow_state like '%%passed'
    """
    sweep_num_list = iclamp_st["sweep_number"].sort_values().tolist()
    results = lq.query(passed_sql, (specimen_id, sweep_num_list))
    # results_df = pd.DataFrame(results, columns=["sweep_number"])
    # passed_sweep_nums = results_df["sweep_number"].values
    return [int(res["sweep_number"]) for res in results]
