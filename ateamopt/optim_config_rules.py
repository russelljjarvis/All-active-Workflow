from collections import OrderedDict
from collections import defaultdict
import numpy as np
import statsmodels.api as sm
import itertools

import logging
logger = logging.getLogger(__name__)


select_feat_dict = {'spike_proto': 2,
                    'nospike_proto': 0}


def filter_feat_proto_active(features_dict, protocols_dict, **kwargs):
    """
        Filter the features and protocols for the final
        stage of optimization
    """
    spiking_proto_dict = OrderedDict()
    non_spiking_proto_dict = OrderedDict()
    training_stimtype_reject = ['LongDCSupra', 'Ramp', 'Short_Square_Triple', 'Noise']

    for feat_key, feat_val in features_dict.items():
        if any(reject_stim in feat_key for reject_stim in training_stimtype_reject):
            continue
        stim_amp = protocols_dict[feat_key]['stimuli'][0]['amp']
        if feat_val['soma']['Spikecount'][0] > 0:
            spiking_proto_dict[feat_key] = stim_amp
#            del feat_val['soma']['Spikecount']
        else:
            non_spiking_proto_dict[feat_key] = stim_amp
            if 'depol_block' in feat_val['soma'].keys():
                del feat_val['soma']['depol_block']

    # Ignoring spiking protocol which are followed by non-spiking stim protocol
    max_nospiking_amp = max(non_spiking_proto_dict.values())
    f_key_list = []
    for spike_stim, spike_amp in spiking_proto_dict.items():
        if spike_amp < max_nospiking_amp:
            f_key_list.append(spike_stim)
    spiking_proto_dict = entries_to_remove(f_key_list, spiking_proto_dict)

    spiking_proto_sorted = sorted(spiking_proto_dict,
                                  key=spiking_proto_dict.__getitem__)
    non_spiking_proto_sorted = sorted(non_spiking_proto_dict,
                                      key=non_spiking_proto_dict.__getitem__)

    num_spike = select_feat_dict['spike_proto']  # In descending order
    num_nospike = select_feat_dict['nospike_proto']  # in descending order

    # Select spiking proto
    try:
        spiking_proto_select = spiking_proto_sorted[len(spiking_proto_sorted)-num_spike:
                                                    len(spiking_proto_sorted)]
    except:
        logger.debug('Number of spiking protocols requested exceeds data')
        spiking_proto_select = spiking_proto_sorted

    # Select nospiking proto
    try:
        nonspiking_proto_select = non_spiking_proto_sorted[len(non_spiking_proto_sorted) -
                                                           num_nospike:len(non_spiking_proto_sorted)]
    except:
        logger.debug('Number of nonspiking protocols requested exceeds data')
        nonspiking_proto_select = non_spiking_proto_sorted

    if kwargs.get('add_fi_kink'):
        spiking_proto_select.append(
            spiking_proto_sorted[0])  # the fist spiking stim
        nonspiking_proto_select.append(
            non_spiking_proto_sorted[-1])  # the last non-spiking stim
        spiking_proto_select = list(set(spiking_proto_select))
        nonspiking_proto_select = list(set(nonspiking_proto_select))

    train_features_dict = {key: val for key, val in features_dict.items()
                           if key in spiking_proto_select +
                           nonspiking_proto_select}
    train_protocols_dict = {key: val for key, val in protocols_dict.items()
                            if key in spiking_proto_select +
                            nonspiking_proto_select}
    test_features_dict = {key: val for key, val in features_dict.items()
                          if key not in spiking_proto_select +
                          nonspiking_proto_select}

    # For fI kink spiking proto only allow the following features
    # Remove everything other than basic features for the first spiking proto
#    f_key_list = []
#    for f_key, f_val in train_features_dict[spiking_proto_sorted[0]]['soma'].items():
#        if f_key not in ['mean_frequency', 'Spikecount','depol_block',
#                         'check_AISInitiation']:
#            f_key_list.append(f_key)
#    train_features_dict[spiking_proto_sorted[0]]['soma'] = entries_to_remove(
#        f_key_list, train_features_dict[spiking_proto_sorted[0]]['soma'])

    if kwargs.get('depol_block_check'):
        max_proto_key = spiking_proto_sorted[-1]
        max_amp = max([proto['amp']
                       for proto in protocols_dict[max_proto_key]['stimuli']])
        DB_proto_delay = max(
            [proto['delay'] for proto in protocols_dict[max_proto_key]['stimuli']])
        DB_proto_duration = min(
            [proto['duration'] for proto in protocols_dict[max_proto_key]['stimuli']])
        DB_proto_stimend = min(
            [proto['stim_end'] for proto in protocols_dict[max_proto_key]['stimuli']])
        DB_proto_totdur = min([proto['totduration']
                               for proto in protocols_dict[max_proto_key]['stimuli']])

        DB_holding_proto = [proto for proto in protocols_dict[max_proto_key]['stimuli']
                            if proto['delay'] == 0]
        DB_proto_dict = [{
            'type': 'SquarePulse',
            'amp': max_amp + 0.01,
                    'delay': DB_proto_delay,
                    'duration': DB_proto_duration,
                    'stim_end': DB_proto_stimend,
                    'totduration': DB_proto_totdur
        }]
        if bool(DB_holding_proto):
            DB_proto_dict.append(DB_holding_proto[0])
        DB_feature_dict = {
            'depol_block': [1.0,
                            0.05]
        }
        train_features_dict['DB_check_DC'] = {'soma': DB_feature_dict}
        train_protocols_dict['DB_check_DC'] = {'stimuli': DB_proto_dict}
#        all_protocols_dict['DB_check_DC'] = {'stimuli':DB_proto_dict}

        return train_features_dict, test_features_dict, train_protocols_dict, DB_proto_dict
    else:
        return train_features_dict, test_features_dict, train_protocols_dict


def filter_feat_proto_basic(features_dict, protocols_dict):
    features_dict = correct_voltage_feat_std(features_dict)
    training_stimtype_reject = ['LongDCSupra', 'Ramp',
                                'Short_Square_Triple', 'Noise', 'DB_check_DC']
    feature_reject = ['time_to_first_spike', 'ISI_CV', 'adaptation_index2',
                      'depol_block']

    spiking_proto_select = []
    for feat_key, feat_val in features_dict.items():
        if any(reject_stim in feat_key for reject_stim in training_stimtype_reject):
            continue
        spiking_proto_select.append(feat_key)

    features_dict_filtered = {key: val for key, val in features_dict.items()
                              if key in spiking_proto_select}
    protocols_dict_filtered = {key: val for key, val in protocols_dict.items()
                               if key in spiking_proto_select}

    for filtered_key, filtered_val in features_dict_filtered.items():
        filtered_val['soma'] = entries_to_remove(
            feature_reject, filtered_val['soma'])

    features_dict_filtered = {key: val for key, val in
                              features_dict_filtered.items() if bool(val['soma'])}
    return features_dict_filtered, protocols_dict_filtered


def filter_feat_proto_passive(features_dict, protocols_dict, **kwargs):
    spiking_proto = []
    for feat_key, feat_val in features_dict.items():
        if feat_val['soma']['Spikecount'][0] > 0:
            spiking_proto.append(feat_key)
        del feat_val['soma']['Spikecount']

    train_features_dict = {key: val for key, val in features_dict.items()
                           if key not in spiking_proto}
    train_protocols_dict = {key: val for key, val in protocols_dict.items()
                            if key not in spiking_proto}
    test_features_dict = {key: val for key, val in features_dict.items()
                          if key not in train_features_dict.keys()}
    return train_features_dict, test_features_dict,\
        train_protocols_dict


def correct_voltage_feat_std(features_dict,
                             feature_correct_list=['voltage_base', 'steady_state_voltage',
                                                   'voltage_after_stim', 'decay_time_constant_after_stim']):
    feature_stat = defaultdict(list)
    feature_keys = []

    for key, val in features_dict.items():
        for feat_name in val['soma'].keys():
            feature_val_list = val['soma'][feat_name][-1]
            if len(feature_val_list) == 1:  # this means no repetition
                # if the feature is in the correction list add it to the std correction
                if feat_name in feature_correct_list:
                    feature_stat[feat_name].append(val['soma'][feat_name][0])
                    feature_keys.append(key)
                # else:
                #     mean = val['soma'][feat_name][0]
                #     val['soma'][feat_name][1] = 0.05*np.abs(mean) if mean != 0 else .05

    feature_keys = list(set(feature_keys))

    for feat_key in feature_keys:
        for feat_name in feature_correct_list:
            if feat_name in features_dict[feat_key]['soma'].keys():
                features_dict[feat_key]['soma'][feat_name][1] = np.std(
                    feature_stat[feat_name]) or 0.05

    return features_dict


def correct_feat_statistics(features_dict, protocols_dict, feat_reject_list=['peak_time'],
                            subthresh_features=['voltage_deflection_vb_ssse',
                                                'decay_time_constant_after_stim'], suprathresh_features=['Spikecount']):

    feature_stat = defaultdict(list)
    protocol_stat = defaultdict(list)
    feature_revision_stims = defaultdict(list)

    for key, val in features_dict.items():
        if key.rsplit('_', 1)[0] == 'LongDC':
            for feat_name in val['soma'].keys():
                if feat_name not in feat_reject_list:
                    if feat_name in subthresh_features and val['soma']['Spikecount'][0] > 0:
                        continue
                    elif feat_name in suprathresh_features and val['soma']['Spikecount'][0] == 0:
                        continue
                    feature_val_list = val['soma'][feat_name][-1]
                    stim_amp = protocols_dict[key]['stimuli'][0]['amp']
                    if len(list(itertools.chain.from_iterable(feature_val_list))) == 1:
                        feature_revision_stims[feat_name].append(key)
                    for feat_list in feature_val_list:
                        feature_stat[feat_name].extend(feat_list)
                        protocol_stat[feat_name].extend([stim_amp]*len(feat_list))

    feature_keys = list(set(feature_stat.keys()))

    for feat_name in feature_keys:
        feature_vals = feature_stat[feat_name]
        protocol_vals = protocol_stat[feat_name]
        model = sm.OLS(feature_vals, sm.add_constant(protocol_vals))
        results = model.fit()
        for stim in feature_revision_stims[feat_name]:
            val = features_dict[stim]
#            if stim.rsplit('_',1)[0] == 'LongDC':
#                if feat_name in val['soma'].keys():

            # Don't correct subthresh specific features for spiking traces
            if feat_name in subthresh_features and val['soma']['Spikecount'][0] > 0:
                continue
            # Don't correct suprathresh specific features for non-spiking traces
            elif feat_name in suprathresh_features and val['soma']['Spikecount'][0] == 0:
                continue
#                    stim_amp = protocols_dict[key]['stimuli'][0]['amp']
#                    se_mean = (results.get_prediction([1,stim_amp]).se_mean[0] or
#                               0.05*np.abs(val['soma'][feat_name][0]) or 0.05)
            # Use rmse only when there is no repetition within and across sweeps
            resid_rmse = np.sqrt(results.mse_resid/results.df_resid)
            if np.isnan(resid_rmse):
                std_corrected = 0.05*np.abs(val['soma'][feat_name][0]) or 0.05
            else:
                std_corrected = (resid_rmse or 0.05*np.abs(val['soma'][feat_name][0]) or 0.05)
            features_dict[stim]['soma'][feat_name][1] = std_corrected
    return features_dict


def adjust_param_bounds(model_param, model_param_prev, tolerance=0.5):
    lb_, ub_ = model_param['bounds']
    value = model_param_prev['value']
    if tolerance > 0:
        lb = max(value - tolerance*abs(value), lb_)
        ub = min(value + tolerance*abs(value), ub_)
        adjusted_bound = [lb, ub]
        model_param['bounds'] = adjusted_bound
    elif tolerance == 0:  # freeze parameters for next stage
        del model_param['bounds']
        model_param['value'] = value
    else:
        raise Exception('Tolerance for parameter bounds has to be positive')
    return model_param


def entries_to_remove(entries, the_dict):
    for key in entries:
        if key in the_dict.keys():
            del the_dict[key]
    return the_dict
