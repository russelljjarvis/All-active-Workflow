#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Created on Mon Feb  5 15:40:38 2018

@author: anin
"""

import bluepyopt as bpopt
import argparse
import logging
import os
import sys
import textwrap
import json
from datetime import datetime
from shutil import copyfile

import evaluator_helper
import checkpoint_decider


if os.path.exists('time_info_back_up.txt'):
    copyfile('time_info_back_up.txt', 'time_info.txt')

logging.basicConfig(level=logging.DEBUG) 
logger = logging.getLogger()


with open('config_file.json') as json_file:  
    path_data = json.load(json_file)
    
morph_path = path_data['morphology']
protocol_path = path_data['protocols']
all_protocol_path = path_data['all_protocols']
mech_path = path_data['mechanism']
mech_release_path = path_data['mechanism_release']
feature_path = path_data['features']
param_path = path_data['parameters']
original_release_param = path_data['original_parameters']


def create_optimizer(args):
    '''returns configured bluepyopt.optimisations.DEAPOptimisation'''
    
    if args.ipyparallel or os.getenv('CELLBENCHMARK_USEIPYP'):
        from ipyparallel import Client
        rc = Client(profile=os.getenv('IPYTHON_PROFILE'))
        
        logger.debug('Using ipyparallel with %d engines', len(rc))
        lview = rc.load_balanced_view()

        def mapper(func, it):
            start_time = datetime.now()
            ret = lview.map_sync(func, it)
            logger.debug('Generation took %s', datetime.now() - start_time)
            f =  open('time_info.txt','a')
            f.write('%s\n'%(datetime.now() - start_time))
            f.close()
            copyfile('time_info.txt', 'time_info_back_up.txt')
            return ret

        map_function = mapper
    else:
        map_function = None
               
    seed = os.getenv('BLUEPYOPT_SEED', args.seed)    
    if args.analyse:
        
        evaluator = evaluator_helper.create(all_protocol_path, feature_path, morph_path, 
                                        param_path, mech_path)
        evaluator_release =  evaluator_helper.create(all_protocol_path, feature_path, morph_path, 
                                        original_release_param, mech_release_path)
    else:
            
        evaluator = evaluator_helper.create(protocol_path, feature_path, morph_path, 
                                        param_path, mech_path)
        
        opt = bpopt.optimisations.DEAPOptimisation(
                evaluator=evaluator,
                map_function=map_function,
                seed=seed)
        return opt
    
    opt = bpopt.optimisations.DEAPOptimisation(
        evaluator=evaluator,
        map_function=map_function,
        seed=seed)
    opt_release = bpopt.optimisations.DEAPOptimisation(
        evaluator=evaluator_release,
        map_function=map_function,
        seed=seed)

    return opt,opt_release
    


def get_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Cell Optimization Example',
        epilog=textwrap.dedent('''\
The folling environment variables are considered:
    CELLBENCHMARK_USEIPYP: if set, will use ipyparallel
    IPYTHON_PROFILE: if set, used as the path to the ipython profile
    BLUEPYOPT_SEED: The seed used for initial randomization
        '''))
    parser.add_argument('--start', action="store_true")
    parser.add_argument('--continu', action="store_true", default=False)
    parser.add_argument('--checkpoint', required=False, default=None,
                        help='Checkpoint pickle to avoid recalculation')
    parser.add_argument('--offspring_size', type=int, required=False, default=2,
                        help='number of individuals in offspring')
    parser.add_argument('--max_ngen', type=int, required=False, default=2,
                        help='maximum number of generations')
    parser.add_argument('--responses', required=False, default=None,
                        help='Response pickle file to avoid recalculation')
    parser.add_argument('--response_release', required=False, default=None,
                        help='Response pickle file to avoid recalculation')
    parser.add_argument('--analyse', action="store_true")
    parser.add_argument('--compile', action="store_true")
    parser.add_argument('--seed', type=int, default=1,
                        help='Seed to use for optimization')
    parser.add_argument('--ipyparallel', action="store_true", default=False,
                        help='Use ipyparallel')
    parser.add_argument('-v', '--verbose', action='count', dest='verbose',
                        default=0, help='-v for INFO, -vv for DEBUG')

    return parser

    
    
def main(): 
    """Main"""
    args = get_parser().parse_args()

    if args.verbose > 2:
        sys.exit('cannot be more verbose than -vv')
    logging.basicConfig(level=(logging.WARNING,
                               logging.INFO,
                               logging.DEBUG)[args.verbose],
                        stream=sys.stdout)
    
    if args.analyse:
        opt,opt_release = create_optimizer(args)
    else:
        opt = create_optimizer(args)

    if args.compile:
        logger.debug('Doing compile')
        import commands
        commands.getstatusoutput('nrnivmodl modfiles/')

    if args.start or args.continu:
        logger.debug('Doing start or continue')
        opt.run(max_ngen=args.max_ngen,
                offspring_size=args.offspring_size,
                continue_cp=args.continu,
                cp_filename=args.checkpoint)
        
    
    if args.analyse:
        logger.debug('Doing analyse')
        import optim_analysis
        cp_dir = args.checkpoint.split('/')[0]
        args.checkpoint = checkpoint_decider.best_seed(cp_dir)
        
        if args.checkpoint is not None and os.path.isfile(args.checkpoint):
#            logger.debug('Checking for Depolarization block for enhanced stimulus')
#            DB_protocol_path = 'DB_protocols.json'
#            DB_response_path = 'DB_response.pkl'
#            hof_index = optim_analysis.DB_check(args.checkpoint,DB_protocol_path,DB_response_path)
#            
#            if hof_index is None:
#                hof_index = 0
#                logger.debug('None passed Depolarization block check')
            
            hof_index = 0
            logger.debug('Plotting Response Comparisons')
            optim_analysis.plot_Response(opt,opt_release,args.checkpoint,
                         args.responses,args.response_release,hof_index)
            logger.debug('Plotting Feature Comparisons')
            optim_analysis.feature_comp(opt,opt_release,args.checkpoint,args.responses,
                                        args.response_release)
            
        else:
            logger.debug('No checkpoint file available run optimization '
                  'first with --start')

        logger.debug('Plotting Parameters - Optimized and Released')

        if not os.path.exists(args.checkpoint):
            raise Exception('Need a pickle file to plot the parameter diversity')

        optim_analysis.plot_diversity(opt, args.checkpoint,
                                     opt.evaluator.param_names,hof_index)
        
        logger.debug('Plotting Evolution of the Objective')
        optim_analysis.plot_GA_evolution(args.checkpoint)
        
        logger.debug('Plotting Spike shapes and mean frequency comparison')
        optim_analysis.post_processing(args.checkpoint,args.responses,hof_index)
        


if __name__ == '__main__':
    main()