#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Created on Wed Aug 29 16:46:19 2018

@author: anin
"""

import numpy as np
from matplotlib import pyplot as plt
from matplotlib import animation
import pickle
from matplotlib import gridspec

plt.style.use('fivethirtyeight')
individual_responses = pickle.load(open('opt_resp_ind.pkl','r'))
individual_fitness = pickle.load(open('selected_fitness.pkl','r'))
frame_num = len(individual_fitness)

key ='LongDC_46'
name_loc = key + '.soma.v'

FileName = 'preprocessed/' + key+ '.txt'
data = np.loadtxt(FileName)
experiment_time = data[:,0]
experiment_voltage = data[:,1]

selected_individuals_response  = []

fig, (ax,ax2) = plt.subplots(1,2,figsize=(8,6),gridspec_kw = {'width_ratios':[9, 1]})
fig.subplots_adjust(hspace=0.2)
line1, = ax.plot([], [], lw=2, color='black', label= 'Experiment')
line2, = ax.plot([], [], lw=2, color='blue', label = 'GA individual')
lines = [line1, line2]
bar_width = 0.2
opacity = 0.5
rects = ax2.bar([0], [0], bar_width, alpha=opacity,color='r')

dpi = 80    
Writer = animation.writers['ffmpeg']
metadata = dict(artist='Matplotlib')

# Change the video bitrate as you like and add some metadata.
writer = Writer(fps = 1,bitrate=-1, metadata=metadata)

def init():
    for line in lines:
        line.set_data([],[])
    return lines
ax.set_ylim(-100, 50)
ax.set_xlim(200, 1350)
fig.legend(handles = (line1,line2), loc = 'upper center', 
           ncol=2, fontsize = 16)
ax.set_xlabel('Time')
ax.set_ylabel('Membrane Potential (mV)')
ax2.get_xaxis().set_visible(False)
ax2.yaxis.set_label_position("right")
ax2.set_ylabel('Error')
ax2.grid('off')
ax2.set_facecolor('white')
ax2.set_ylim(0, 1000)
ax2.set_yticks([0,500])
plt.tight_layout()

def animate(i):
    response_GA = individual_responses[i]
    time = np.asarray(response_GA[name_loc]['time'])
    voltage = np.asarray(response_GA[name_loc]['voltage'])
    lines[0].set_data(experiment_time, experiment_voltage)
    lines[1].set_data(time, voltage)
    for rect in rects:
        rect.set_height(individual_fitness[i])
    return lines,rect

anim = animation.FuncAnimation(fig, animate, init_func=init, frames=frame_num, 
                               interval=25)
anim.save('GA_Animation.mp4', writer=writer, dpi = dpi)
plt.show()


#if __name__ == '__main__':
#    Main()