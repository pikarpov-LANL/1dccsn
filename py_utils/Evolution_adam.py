# This is an analysis script that can:
#     1. convert binary output to readable [.txt]
#     2. produce time evolution plots for selected variables
#     3. produce summary plots of 
#       - the convection region grid size post-bounce
#       - time evolution of electron neutrinos flux
#       - PNS radius and shock position evolution
#       - shock position vs. time with mass shells
#     4. combines all of the plots into movies with ffmpeg
#
# and all of this in parllel with MPI. For examples, to run on 4 cores:
#
# mpirun -n 4 python Evolution_plots_mpi.py
#    
# -pikarpov

import os
import sys
import time
import shutil
from subprocess import Popen, PIPE
from mpi4py import MPI
import h5py as h5

sys.path.append("/home/pkarpov/Sapsan")

import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
from sapsan.utils import line_plot, plot_params

# Resolution: 678x128x256 (r x theta x phi): r, pi and 2pi respectively
# outter radius is 2e4 km (2e9 cm)

#comp0: Ye
#eos0: gas pressure
#eos1: sound speed
#eos2: Temperature
#eos3: entropy
#eos4: gamma_1
#The rad variables of relevance are Erad0, Erad1, Erad2 (0, 1, 2 corresponding to electron neutrinos, electron anti-neutrinos, and heavy neutrinos) energy densitivies, and analgously for Frad0,1,2.

#['Flux0_0', 'Flux0_1', 'Flux0_2', 'Flux1_0', 'Flux1_1', 'Flux1_2', 
#'Flux2_0', 'Flux2_1', 'Flux2_2', 'Pturb_s2', 'Time', 'comp0', 
#'eos0', 'eos1', 'eos2', 'eos3', 'eos4', 
#'lapse', 'lapse_edge', 'rho', 'u', 'u1', 'u2', 'u3', 
#'velocity0', 'velocity1', 'velocity2']

def main():
    # --- Datasets and values to plot ---
    vals             = [
                        # 'pturb',
                        # 'u1',                                               
                        # 'rho',
                        # 'sound',                        
                        'vturb',    
                        # 'vturb2',                                             
                        # 'u2',
                        # 'u3',                        
                        # 'ye',
                        # 'pressure',                        
                        # 'temperature',
                        # 'entropy',                        
                        # 'u_int',                        
                        # 'mach',
                        # 'pturb_pgas'
                       ]
    versus           = 'r'   # options are either 'r' or 'encm' for enclosed mass
    
    masses           = [9.0,10.0,12.0,13.0,14.0,15.0,16.0,17.0,18.0,19.0,20.0] # for g9k and g2k 

    # --- Paths & Names ---        
    base             = 'swbj15.horo.3d'
    
    end              = ''
    datasets         = [f's{m}.{base}{end}' for m in masses]
    
    base_path        = '/scratch/pkarpov/adam/'
    
    base_file        = f'dump'
    save_name_amend  = ''      # add a custom index to the saved plot names
    
    # --- Extra ---
    convert2read     = False   # convert binary to readable (really only needed to be done once) 
    only_last        = True   # only convert from the latest binary file (e.g., latest *_restart_*)
    only_post_bounce = True    # only produce plots after the bounce    
    
    # --- Compute Bounce Time, PNS & Shock Positions ---
    compute          = True
    rho_threshold    = 1e12    # for the PNS radius - above density is considered a part of the Proto-Neutron Star

    # --- Plots & Movie Parameters ---
    dpi              = 80      # increase for production plots
    make_movies      = True 
    fps              = 10   
    save_plot        = True
    
    # --- Path to readout executable ---
    readout_path     = '../project/1dmlmix' # should be in the main code folder
    
    # === No need to go beyond this point ===========================

    # --- MPI setup ---
    comm = MPI.COMM_WORLD
    size = comm.Get_size()
    rank = comm.Get_rank()    
    
    if rank==0: 
        colored.head(f'\n=====================================')
        colored.head(f'PATH: {base_path}')
        colored.head(f'=====================================\n')
        
    # convert datasets in parallel
    if convert2read:# and len(datasets)>1:
        if rank == 0:
            colored.head('<<< Converting Binary to Readable >>>')
            if only_last: print(f'Only Last: {only_last}')
            interval = get_interval(size, len(datasets))
                       
            for i in range(size):
                for j in range(interval[i][0], interval[i][1]):
                    rd = Readout(i, base_path, datasets[j], base_file, readout_path, only_last)    
                    rd.copy_readout()
                                                
        else: intervaplot_gridl = 0                   
        
        interval = comm.scatter(interval, root=0)
        if rank < len(datasets): print(f'Rank',f'{rank}'.ljust(2, ' '),f'got {datasets[interval[0]:interval[1]]}')
        if rank == 0: time.sleep(0.1); print()
        
        for j in range(interval[0], interval[1]):  
            dataset  = datasets[j]                                                            
            rd       = Readout(rank, base_path, dataset, base_file, readout_path, only_last)
            numfiles = rd.run_readable()
            
        comm.Barrier()
        time.sleep(0.1)

        if rank == 0: 
            rd.clean(); print()
                  
    # calculate metrics and produce plots
    for dataset in datasets:
        
        # --- Create initial assignment ---
        if rank == 0:                              
            colored.head(f'<<<<<<<<< {dataset} >>>>>>>>>')
            
            numfiles = get_numfiles(base_path, dataset, base_file)
            
            if numfiles==0: colored.error('No readable files found; try setting convert2read = True'); comm.Abort()

            colored.subhead('--------- Summary ---------')
            print(f'Total number of files:  {numfiles}') 
            
            last_file = numfiles 
                    
            pf = Profiles(rank = rank, numfiles = numfiles, 
                          base_path = base_path, base_file = base_file, dataset = dataset,
                          save_name_amend=save_name_amend, only_post_bounce = only_post_bounce)
                     
            # bounce_delay is in [s]         
            bounce_files = numfiles #pf.check_bounce(compute=compute, bounce_delay=2e-3)
            bounce       = pf.bounce_ind      
            if only_post_bounce:                   
                shift        = bounce
                numfiles     = bounce_files                                                          
            else:
                shift = get_first_dump(base_path, dataset, base_file)
                numfiles -= 1
                
            print(f'Bounce at file:         {bounce+1}')
            print(f'Post bounce files:      {bounce_files}')  
                        
            colored.subhead( '\n-------- Intervals --------')
            interval  = get_interval(size, numfiles)                                  
                        
            interval += shift
            numfiles += shift
            last_file = numfiles
            
            # creates (if needed) directories to store all plots
            if save_plot: [pf.set_paths(val, versus, check_path=True) for val in vals]                
            pf.plot_grid(vals,idump=1) 
                                                     
        else:
            last_file = 0
            interval  = 0   
            shift     = 0 
            bounce    = 0   
            
        numfiles = comm.bcast(last_file, root=0)
        interval = comm.scatter(interval, root=0)    
        
        # numfiles = 1
        # interval = [0,1] 
        # bounce   = 0  
        
        pf = Profiles(rank = rank, numfiles = numfiles, 
                      base_path = base_path, base_file = base_file, dataset = dataset,
                      save_name_amend=save_name_amend, only_post_bounce = only_post_bounce, 
                      interval = interval, dpi = dpi)

        if not only_post_bounce: pf.bounce_ind = comm.bcast(bounce, root=0)
        else: pf.bounce_ind = comm.bcast(shift, root=0)

        print('rank',f'{rank}'.ljust(2, ' '),f': interval {interval}')

        comm.Barrier()
        time.sleep(0.1)
        if rank == 0: colored.subhead( '\n-------- Progress ---------')

        if not make_movies:
            # --- Main Parallel Loop ---
            for i in range(interval[0], interval[1]):  
                pf.plot_profile(i             = i, 
                                vals          = vals, 
                                versus        = versus, 
                                show_plot     = False, 
                                save_plot     = save_plot,
                                compute       = compute,
                                rho_threshold = rho_threshold
                            )     

            pf.progress_bar(i+1, 'Done!', done = True)           
            
            gather_pns_ind    = comm.gather(pf.pns_ind_ar,    root=0)
            gather_pns_x      = comm.gather(pf.pns_x_ar,      root=0)
            gather_pns_encm   = comm.gather(pf.pns_encm_ar,   root=0)
            gather_shock_ind  = comm.gather(pf.shock_ind_ar,  root=0)
            gather_shock_x    = comm.gather(pf.shock_x_ar,    root=0)
            gather_shock_encm = comm.gather(pf.shock_encm_ar, root=0)
            gather_lumnue     = comm.gather(pf.lumnue,        root=0)
            gather_lumnueb    = comm.gather(pf.lumnueb,       root=0)
            gather_lumnux     = comm.gather(pf.lumnux,        root=0)        
            gather_shell      = comm.gather(pf.shell_ar,      root=0)
            gather_time       = comm.gather(pf.time_ar,       root=0)        
            
            # --- Back to Rank 0 to produce Summary Plots ---
            if rank == 0: 
                colored.subhead( '\n----------- Plots ----------')
                print(f'{pf.base_save_path}\n') 
                        
                pf.pns_ind_ar    = sum(gather_pns_ind)
                pf.pns_x_ar      = sum(gather_pns_x)
                pf.pns_encm_ar   = sum(gather_pns_encm)
                pf.shock_ind_ar  = sum(gather_shock_ind)
                pf.shock_x_ar    = sum(gather_shock_x)
                pf.shock_encm_ar = sum(gather_shock_encm)
                pf.lumnue        = sum(gather_lumnue)
                pf.lumnueb       = sum(gather_lumnueb)
                pf.lumnux        = sum(gather_lumnux)  
                pf.shell_ar      = sum(gather_shell)
                pf.time_ar       = sum(gather_time)          
                # pf.bounce_ind    = shift
                
                if versus == 'r': 
                    pf.save_evolution()
                    if pf.bounce_ind > 0:
                        pf.plot_convection()
                        pf.plot_pns_shock()
                        # pf.plot_shells()                
                            
                # pf.plot_lumnue()                                    
                
        else:            
            # --- Movies are produced in parallel ---            
            if rank == 0: 
                colored.subhead('\n---------- Movies ----------')
                if not os.path.exists(pf.movie_save_path): os.makedirs(pf.movie_save_path)
                print(f'{pf.movie_save_path}\n')     
                interval = get_interval(size, len(vals), printout=False)
            else: interval = 0
            
            interval = comm.scatter(interval, root=0)
                           
            for i in range(interval[0], interval[1]):                 
                val = vals[i]
                if val == 'encm' and versus == 'encm': continue
                if shift != 0: start=shift
                else: start = 1
                pf.movie(val,versus=versus,fps=fps,start=start)

        comm.Barrier()
        time.sleep(0.1)
                        
        if rank == 0: colored.head(f'<<<<<<<<<<< Done >>>>>>>>>>>\n')                

# === Backend ===============================================

def get_interval(size, numfiles, printout=True):
    
    idle = 0
    if size > numfiles:
        idle = size - numfiles
        if printout: colored.warn(f'not enough work for all ranks - {idle} will idle during conversion\n')
        size = numfiles
        
    interval_size = int(numfiles/size)
    leftover      = numfiles%size
    
    if printout:
        print(f'Average interval size:  {interval_size}')
        print(f'Leftover to distribute: {leftover}\n')    
    
    interval = np.array([[i*interval_size,i*interval_size+interval_size] for i in range(size)])
    
    if leftover != 0: interval = spread_leftovers(interval, leftover, size)
    
    if idle != 0:
        while len(interval)<(size+idle):
            interval = np.concatenate((interval, np.array([[0,0]])))
    
    return interval
                        
def spread_leftovers(interval, leftover, size):    
    shift = 0
    for i in range(size):        
        interval[i,0] += shift
        if leftover != 0:
            shift    += 1
            leftover -= 1             
        interval[i,1] += shift
    return interval

def get_numfiles(base_path, dataset, base_file):
    numfiles = len([filename for filename in os.listdir(f'{base_path}{dataset}') if base_file in filename])
    return numfiles

def get_first_dump(base_path, dataset, base_file):
    alldumps = [filename for filename in os.listdir(f'{base_path}{dataset}') if base_file in filename]
    alldumps = [int(filename.split('.')[-1]) for filename in alldumps]

    return min(alldumps)-1

class Readout:
    def __init__(self, rank, base_path, dataset, base_file, readout_path, only_last=False):
        self.rank             = rank
        self.base_path        = base_path
        self.dataset          = dataset
        self.readout_path     = readout_path                
        self.base_file        = base_file
        self.only_last        = only_last
        self.cwd              = os.getcwd()
        self.tmp_path         = f'{self.cwd}/tmp/{self.rank}'        
        self.full_output_path = f'{self.base_path}{self.dataset}'        

    def run_readable(self):
        # print( '---- Converting Binary ----')
        
        self.tmp_path += f'/{self.dataset}'
        for outfile in self.get_all_outfiles():
    
            # self.status(outfile, done=False)                                
                        
            self.setup_readout(outfile)
                                                
            os.chdir(self.tmp_path)
            
            p = Popen('./readout', shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
            output = p.stdout.read()
            p.stdout.close()
            
            os.chdir(self.cwd)
            
            # self.status(outfile, done=True)
            
            print(f'Rank',f'{self.rank}'.ljust(2, ' '),f'converted {self.dataset}: {outfile}')
                        
        return get_numfiles(self.base_path, self.dataset, self.base_file)
    
    def get_all_outfiles(self):
        outfiles = [filename for filename in os.listdir(f'{self.base_path}{self.dataset}') if ("restart" in filename or filename=='DataOut')]
        if self.only_last:
            if any("restart" in file for file in outfiles):   
                to_remove = 'DataOut'  
                try: outfiles.remove(f'{to_remove}')       
                except: colored.warn(f"No '{to_remove}', only '_restart_'")
                last_num   = max([int(filename.split('_')[-1]) for filename in outfiles])            
                return [f"DataOut_restart_{last_num}"]
        return outfiles

    def copy_readout(self):
        self.tmp_path += f'/{self.dataset}'
        if not os.path.exists(self.tmp_path): os.makedirs(self.tmp_path)
        shutil.copy(f'{self.readout_path}/readout', f'{self.tmp_path}/readout')
        shutil.copy(f'{self.readout_path}/setup_readout', f'{self.tmp_path}/setup_readout')            
        
    def setup_readout(self, outfile):                          
                     
        filepath = f'{self.tmp_path}/setup_readout'
        
        # Edit setup         
        with open(filepath, 'r') as file:    
            data = file.readlines()            
            for i, line in enumerate(data):                
                if 'Data File Name' in line: 
                    data[i+1] = f'{self.full_output_path}/{outfile}\n' 
                if 'Output Basename' in line:                     
                    data[i+1] = f'{self.full_output_path}/{self.base_file}\n'     
                if 'Number of dumps' in line:                     
                    data[i+1] = f'10000\n'                                      
                    
        self.write_data(filepath, data)               
    
    def write_data(self, filepath, data):
        with open(filepath, 'w') as file:   
            file.writelines(data)    
            
    def status(self, outfile, done):
        
        if self.only_last and not done: print(f'Only Last: {self.only_last}')
        
        padding_val = int(20-len(outfile)) * ' '
        msg         = f'Converting {outfile}...{padding_val}'
        ending      = '\n' if done == True else '\r'
        
        if done: print(f'{msg} done', end=ending)
        else: print(f'{msg}', end=ending) 
        
    def clean(self):
        shutil.rmtree(f'{self.cwd}/tmp/')
                
   
class ComputeRoutines:
    #
    # Routines to calculate PNS radius and shock position
    #
    def __init__(self, x, rho, v, vsound=None):
        self.x             = x
        self.rho           = rho
        self.v             = v  
        self.vsound        = vsound              
        self.shock_ind     = 0
        self.shock_x       = 0
        self.pns_ind       = 0
        self.pns_x         = 0                
        
    def shock_radius(self, bump=0, old_shock_ind=-1):                        
                
        # for i in range(len(self.v)-1,4,-1):
        #     if i == len(self.v)-1: 
        #         dv_old = (self.v[i]-self.v[i-5])
        #         continue
            
        #     dv = (self.v[i]-self.v[i-5])                   
        #     if abs(dv) > abs(10*dv_old):
        #         self.shock_ind = i-4
        #         self.shock_x   = self.x[self.shock_ind]
        #         break
            
        #     dv_old = dv
        
        # interval = 100
        
        # if old_shock_ind == -1:                        
        #     self.shock_ind = np.argmin(self.v)
        #     self.shock_x   = self.x[self.shock_ind]
        # else:
        #     self.shock_ind = np.argmin(self.v[old_shock_ind-interval:old_shock_ind+interval])+(old_shock_ind-interval)
        #     self.shock_x   = self.x[self.shock_ind]        
        
        self.shock_ind = bump+np.argmin(self.v[bump:])
        self.shock_x   = self.x[self.shock_ind]
                
        # mach = abs(self.v/self.vsound)
        # mach_threshold = np.amax(mach)/2
        
        # for i in range(np.argmin(self.v),-1,-1):       
        #     if mach[i] < mach_threshold:
        #         self.shock_ind = i
        #         self.shock_x   = self.x[self.shock_ind]
        #         break
    
        #print('shock position: %.2e'%self.shock_x, self.shock_ind)
        return self.shock_ind, self.shock_x
        
    def pns_radius(self, rho_threshold = 2e11):      
          
        for i in range(len(self.rho)):            
            if self.rho[i] > rho_threshold:
                self.pns_ind = i
                self.pns_x   = self.x[i]
                
        return self.pns_ind, self.pns_x        

class Profiles:
    #
    # All things plotting related (+ bounce check)
    #
    def __init__(self, rank, numfiles, base_path, base_file, dataset, 
                 save_name_amend='', only_post_bounce = False, interval=[0,0], 
                 dpi=60, delta_shell = 0.01):
        self.numfiles         = numfiles
        self.lumnue           = np.zeros((self.numfiles))
        self.lumnueb          = np.zeros((self.numfiles))
        self.lumnux           = np.zeros((self.numfiles))
        self.times            = np.zeros((self.numfiles))
        self.base_path        = base_path
        self.dataset          = dataset
        self.base_save_path   = f'{self.base_path}{self.dataset}/plots/'
        self.movie_save_path  = f'{self.base_path}{self.dataset}/movies/'
        self.save_name_amend  = save_name_amend
        self.only_post_bounce = only_post_bounce
        self.interval         = interval
        self.dpi              = dpi
        self.cm2km            = 1e-5
        self.s2ms             = 1e3
        self.msol             = 1.989e33
        self.delta_shell      = delta_shell
        #self.progress_bar(0)
        
        self.pns_ind_ar       = np.zeros(self.numfiles)
        self.pns_x_ar         = np.zeros(self.numfiles)
        self.pns_encm_ar      = np.zeros(self.numfiles)        
        self.shock_ind_ar     = np.zeros(self.numfiles)
        self.shock_x_ar       = np.zeros(self.numfiles)
        self.shock_encm_ar    = np.zeros(self.numfiles)
        self.time_ar          = np.zeros(self.numfiles)
        self.shell_ar         = np.array([])
        self.shell_index      = np.array([])
        self.ind_ar           = np.arange(1, self.numfiles+1)
        self.old_shock_ind    = -1
        self.bounce_ind       = 0
        self.rank             = rank
        self.base_file        = base_file 
        
        # Region constraints to find the correct shock position
        # dict = {checkpoint_index:grid_index}
        if 's16.0_g9k_c8.4k_p_0.3k' in self.dataset:
            self.shock_region = {711:5400, 712:5400, 713:5400, 714:5400,
                                 715:5400, 716:5420, 717:5440, 718:5460,
                                 719:5463}    
        elif 's17.0_g9k_c8.4k_p_0.3k' in self.dataset:
            self.shock_region = {734:5900, 735:5850, 736:5850, 737:5900,
                                 738:5900, 739:5950, 740:5950, 741:5970,
                                 742:5980}   
        elif 's18.0_g9k_c8.4k_p_0.3k' in self.dataset:
            self.shock_region = {663:5350, 664:5350, 665:5350, 666:5370}                                                 
        else: self.shock_region = {}
        
    def progress_bar(self, current, val='', done = False, bar_length=20):
        current -= self.interval[0]
        lastfile = self.interval[1]-self.interval[0]
        fraction = current / lastfile

        arrow       = int(fraction * bar_length - 1) * '-' + '>'
        padding     = int(bar_length - len(arrow)) * ' '
        padding_val = int(12-len(val)) * ' '

        ending = '\n' if done == True else '\r'

        print('rank',f'{self.rank}'.ljust(2, ' '),
              f': [{arrow}{padding}] {current}/{lastfile}, val: {val}{padding_val}', 
              end=ending) 

    def set_paths(self, val, versus, check_path=False):
        self.plot_path = f'{self.base_save_path}{val}'
        
        if check_path: 
            if not os.path.exists(self.plot_path): os.makedirs(self.plot_path)
            
        if   versus == 'r'   : self.versus_name = '_r'
        elif versus == 'rho' : self.versus_name = '_rho'
        elif versus == 'encm': self.versus_name = '_encm'    
        
        self.plot_file = f'{self.plot_path}/{val}{self.versus_name}'

    def check_bounce(self, compute=False, bounce_delay=2e-3):     
        # bounce_delay is in [s]
        self.bounce_ind = -1
        bounced         = 0
        
        # if compute, then the bounce time is unknown: 
        # need to go through each file from the beginning
        if compute:                                     
            for i in range(self.numfiles):
                
                ps, time1d, bounce_time = self.open_checkpoint(i, fullout=False)

                index  = 0
                for h in self.header:            
                    if '[' in h: continue  
                    valname = h.lower()                    
                    if 'rho' in valname: rho = ps[index]
                    index += 1
                
                # check for nuclear density
                if np.amax(rho) > 2e14:
                    if bounced==0: bounced = time1d 
                    if (time1d-bounced) > bounce_delay:
                        self.bounce_ind = i
                        return self.numfiles - self.bounce_ind 
                        
                if bounce_time > 0: 
                    self.bounce_ind = i
                    return self.numfiles - self.bounce_ind
        
        # otherwise grab the bounce time from the last checkpoint 
        # and calculate bounce index from nearby
        else:                        
            ps, time1d_last, bounce_time = self.open_checkpoint(self.numfiles-1, fullout=False)                        
            if bounce_time == 0.0: colored.warn('Bounce has not occured yet'); return -1            
            ps, time1d, dummy = self.open_checkpoint(self.numfiles-2, fullout=False)
            
            dt              = time1d_last-time1d
            anchor_index    = int(bounce_time/dt)+1
            self.bounce_ind = anchor_index             
            
            for i in range(anchor_index,0,-1):
                ps, time1d, bounce_time = self.open_checkpoint(i, fullout=False)
                if bounce_time != 0.0: self.bounce_ind = i
                else: return self.numfiles - self.bounce_ind                                 
                                                                                    
        colored.warn('Bounce has not been found :(')
        return -1
    
    def open_checkpoint(self, i, fullout=True):
        file   = f'{self.base_file}.{i+1}'
        file1d = f'{self.base_path}{self.dataset}/{file}' 
            
        with open(file1d, "r") as file:
            line = file.readline()                                                                                                      
            header_vals = file.readline()
            vals_strip  = header_vals[:-1].split(' ')        
            try: time1d, bounce_time, pns_ind, pns_x, shock_ind, shock_x, rlumnue, rlumnueb, rlumnux = [float(x) for x in vals_strip if x!='']        
            except: 
                time1d, bounce_time, pns_ind, pns_x, shock_ind, shock_x, rlumnue = [float(x) for x in vals_strip if x!='']            
                rlumnueb = 0
                rlumnux  = 0
            self.header = file.readline() 
            self.header = self.header.split(' ')
            self.header = list(filter(None, self.header))            

        pns_ind   = int(pns_ind)-1
        shock_ind = int(shock_ind)-1
                    
        ps = np.genfromtxt(file1d, skip_header=3)
        ps = np.moveaxis(ps,0,1)
                
        if fullout: return ps,time1d,bounce_time,pns_ind,pns_x,shock_ind,shock_x,rlumnue,rlumnueb,rlumnux
        else: return ps,time1d,bounce_time
    
    def save_evolution(self):
        evolution_path = f'{self.base_save_path}{self.save_name_amend}evolution.txt'        
        header         = ('Time [s] \t PNS Index \t PNS Radius [cm] \t PNS Encm [Msol] \t' +
                                    'Shock Index \t Shock Radius [cm] \t Shock Encm [Msol]')
        evolution      = np.array([                                            
                                   self.time_ar,
                                   self.pns_ind_ar,self.pns_x_ar,self.pns_encm_ar,
                                   self.shock_ind_ar, self.shock_x_ar, self.shock_encm_ar,
                                   self.lumnue, self.lumnueb, self.lumnux                                                                                               
                                  ])
        evolution      = np.moveaxis(evolution, -1, 0)
                         
        np.savetxt(evolution_path, evolution, header = header)
        
        # Mass Shells
        evolution_path = f'{self.base_save_path}{self.save_name_amend}evolution_mass_shells.txt'
        header         = ('Time [s] \t Mass Shells Position [cm]')
        evolution      = [self.time_ar]
        
        for s in range(np.shape(self.shell_ar)[-1]):
            evolution.append(self.shell_ar[:,s])            
        
        evolution = np.moveaxis(np.array(evolution), -1, 0)
                                 
        np.savetxt(evolution_path, evolution, header = header)
        
        
    def plot_format(self, series, xlabel, ylabel, title, 
                          plot_style = 'plot', label=None,
                          ax=None, marker='.', linewidth=1.5):                       
        
        style = 'tableau-colorblind10'
        mpl.style.use(style)
        mpl.rcParams.update(plot_params())  
        
        if not label: label = [f'None' for i in range(len(series))]
        
        if ax==None:            
            fig = plt.figure(figsize=(10,6), dpi=self.dpi)
            ax  = fig.add_subplot(111)        
        for idx, data in enumerate(series): 
            if   plot_style == 'plot'    : plot_func = ax.plot
            elif plot_style == 'semilogx': plot_func = ax.semilogx
            elif plot_style == 'semilogy': plot_func = ax.semilogy
            elif plot_style == 'loglog'  : plot_func = ax.loglog  
                      
            plot_func(data[0], data[1], linewidth=linewidth, marker=marker, label=label[idx])
        
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)        
        ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True))
        
        self.sim_label(ax, x = 0.993)
            
        plt.tight_layout()
        if 'None' not in label: ax.legend(loc=0)                       
         
        return ax 
    
    def find_start(self):    
        # checks if there was a delay after bounce to apply turbulent pressure    
        delay = 0
        for i in range(self.bounce_ind, len(self.pns_x_ar)):
            if self.pns_x_ar[i]>0: break
            else: delay+=1                
        return self.bounce_ind + delay                      
    
    def sim_label(self, ax, x = 0.992, y = 1.024):
        #m,res = self.dataset.split('_')[:2]
        m = self.dataset.split('.swb')[0]
        res = 'adam'
        ax.text(x, y, f'{m} | {res}', 
                horizontalalignment='right',transform=ax.transAxes,
                bbox=dict(boxstyle='square', facecolor='white',linewidth=1))  
    
    def plot_grid(self, vals, idump=1, show_plot=False):
        
        valmap, time1d    = self.open_hdf5(idump, vals)
        
        rho = valmap['rho']
        v   = valmap['u1']
        r   = valmap['radius']
        
        udist   = 1e5
        encm    = np.zeros(v.shape)
        dm      = np.zeros(v.shape)
        dm[0]   = rho[0]*4/3*np.pi*(udist*r[0])**3/self.msol
        encm[0] = dm[0]

        for i in range(1,len(v)):
            dm[i]   = 4/3*np.pi*rho[i]*udist**3*(r[i]**3-r[i-1]**3)/self.msol
            encm[i] = encm[i-1] + dm[i]
            
        save_path = f'{self.base_save_path}{self.save_name_amend}grid.png'
        
        ax = self.plot_format(series     = [[encm[1:],dm[1:]]],
                              xlabel     = r'Enclosed Mass [$M_{\odot}$]', 
                              ylabel     = r'Delta Mass [$M_{\odot}$]',
                              title      = r'Grid Size', 
                              plot_style = 'semilogy')
        
        plt.savefig(save_path)        
        if not show_plot: plt.close() 
        
        save_path = f'{self.base_save_path}{self.save_name_amend}grid_zoom.png'
        
        ax = self.plot_format(series     = [[encm[1:],dm[1:]]],
                              xlabel     = r'Enclosed Mass [$M_{\odot}$]', 
                              ylabel     = r'Delta Mass [$M_{\odot}$]',
                              title      = r'Grid Size', 
                              plot_style = 'semilogy',
                              label      = ['grid'])   
        
        for i in range(len(dm)-1):
            if abs(dm[i+1]-dm[i])<dm[i+1]*1e-3:
                ax.axvline(encm[i], color='r',linewidth=1, label=f'start[{i}] = {encm[i]}')
                break
        
        for i in range(len(dm)-2,-1,-1):
            if abs(dm[i+1]-dm[i])<dm[i+1]*1e-3:
                ax.axvline(encm[i], color='r',linewidth=1, linestyle='--',label=f'end[{i}] = {encm[i]}')
                break
        
        ax.set_xlim(1.1,2)
        plt.legend()
        
        plt.savefig(save_path)        
        if not show_plot: plt.close()     
        
    def plot_convection(self, show_plot=False):        
                 
        save_path = f'{self.base_save_path}{self.save_name_amend}convgrid.png'
        
        x = (np.trim_zeros(self.time_ar)-np.trim_zeros(self.time_ar)[0])*self.s2ms

        ax = self.plot_format(series     = [[x, np.trim_zeros(self.shock_ind_ar-self.pns_ind_ar)]],
                              xlabel     = r'$t-t_{bounce}$ [ms]', 
                              ylabel     = 'Convection Grid Size',
                              title      = f'Bounce index = {self.bounce_ind+1}')  
        
        plt.savefig(save_path)        
        if not show_plot: plt.close() 
        
        print(f'Convection  : {self.save_name_amend}convgrid.png')
                            
    
    def plot_lumnue(self, show_plot=False):                  
        
        if self.only_post_bounce: 
            name_amend = '_bounce'      
            x = (np.trim_zeros(self.time_ar)-np.trim_zeros(self.time_ar)[0])*self.s2ms
        else: 
            name_amend = ''
            x = np.trim_zeros(self.time_ar)*self.s2ms
                
        save_path = f'{self.base_save_path}{self.save_name_amend}lumnue{name_amend}.png'                     
        
        start = self.find_start()
        
        ax = self.plot_format(series     = [[x, self.lumnue[start:]],
                                            [x, self.lumnueb[start:]],
                                            [x, self.lumnux[start:]]],
                              xlabel     = r'$t-t_{bounce}$ [ms]', 
                              ylabel     = r'$F_{\nu_{e}} \; [foe/s]$', 
                              title      = f'Bounce index = {self.bounce_ind+1}', 
                              plot_style = 'semilogy',                              
                              label      = ['nue', 'nueb', 'nux']) 
        
        plt.savefig(save_path)        
        if not show_plot: plt.close() 
        
        print(f'lumnue      : {self.save_name_amend}lumnue{name_amend}.png')
                 
                     
    def plot_pns_shock(self, show_plot=False):                  
                
        plot_data = [[self.pns_x_ar[self.bounce_ind:]*self.cm2km,
                      self.pns_encm_ar[self.bounce_ind:]         ],
                     [self.shock_x_ar[self.bounce_ind:]*self.cm2km, 
                      self.shock_encm_ar[self.bounce_ind:]       ]]
        
        labels    = ['pns', 'shock']   
        
        save_path = f'{self.base_save_path}{self.save_name_amend}pns_shock.png'
        
        ax = self.plot_format(series    = plot_data,
                              xlabel    = r'$Radius \; [km]$', 
                              ylabel    = r'$M_{enc} \; [M_{\odot}]$', 
                              title     = f'Bounce index = {self.bounce_ind+1}',
                              label     = labels)  
        
        plt.savefig(save_path)        
        if not show_plot: plt.close() 
        
        print(f'pns_shock   : {self.save_name_amend}pns_shock.png')    
                               
        return ax  
    
    
    def plot_shells(self, show_plot=False):                  

        save_path = f'{self.base_save_path}{self.save_name_amend}mass_shells.png'
        
        plot_data = []
        
        for s in range(np.shape(self.shell_ar)[-1]):
            plot_data.append([(self.time_ar[self.bounce_ind:]-self.time_ar[self.bounce_ind])*self.s2ms, 
                              np.log10(self.shell_ar[self.bounce_ind:,s]*self.cm2km)])
                    
        fig = plt.figure(figsize=(10,6), dpi=self.dpi)
        ax  = fig.add_subplot(111)                    
        for idx, data in enumerate(plot_data): 
            ax.plot(data[0], data[1], linewidth=1.5, color='tab:gray')        
        
        start = self.find_start()

        plot_data = [[(self.time_ar[start:]-self.time_ar[start])*self.s2ms, 
                      np.log10(self.pns_x_ar[start:]*self.cm2km)],
                     [(self.time_ar[start:]-self.time_ar[start])*self.s2ms, 
                      np.log10(self.shock_x_ar[start:]*self.cm2km)]]
        
        labels    = ['PNS', 'Shock'] 
        
        ax.set_ylim(1,3)
        
        ax = self.plot_format(series    = plot_data,
                              xlabel    = r'$t-t_{bounce}$ [s]', 
                              ylabel    = r'log(R) [km]', 
                              title     = f'Bounce index = {self.bounce_ind+1}',
                              label     = labels,
                              ax        = ax,
                              marker    = '',
                              linewidth = 2.5)    
        
        plt.savefig(save_path)        
        if not show_plot: plt.close()              
        
        print(f'mass_shells : {self.save_name_amend}mass_shells.png')    
                                    
        return ax
    
    def open_hdf5(self,i,vals):
        file   = self.base_file+'_%05d.h5'%(i)
        
        file1d = f'{self.base_path}{self.dataset}/{file}'      
        
        if not os.path.exists(file1d): return None, None
                
        valnames = {'u1'      : 'u1'           ,
                    'u2'      : 'u2'           ,
                    'u3'      : 'u3'           ,
                    'u'       : 'u_int'        ,
                    'rho'     : 'rho'          , 
                    'comp0'   : 'ye'           ,
                    'eos0'    : 'pressure'     ,
                    'eos1'    : 'sound'        ,
                    'eos2'    : 'temperature'  ,
                    'eos3'    : 'entropy'      ,
                    'Pturb_s2': 'pturb'}
        
        valmap = {}
        
        with h5.File(file1d, 'r') as hf:
            time1d = np.array(hf['Time'])[0]
            for j,val in enumerate(valnames.keys()):                
                valmap[valnames[val]] = np.array(hf[val])
                
        valmap['mach']       = np.absolute(valmap['u1']/valmap['sound'])
        valmap['vturb']      = np.sqrt(valmap['pturb']/valmap['rho'])
        valmap['vturb2']     = valmap['vturb']**2
        valmap['pturb_pgas'] = valmap['pturb']/valmap['pressure']
                
        grid = f'{self.base_path}{self.dataset}/grid.h5'
        with h5.File(grid, 'r') as hf:
            valmap['radius'] = np.array(hf['Z'])
                
        return valmap, time1d
               
                    
    def plot_profile(self, i, vals, versus,
                     show_plot=False, save_plot=False, 
                     compute=False, rho_threshold = 2e11):        

        valmap, time1d    = self.open_hdf5(i, vals)
        if valmap == None: return
        
        self.times[i] = time1d    
        bounce_time = 0
                                
        r    = valmap['radius'][1:]                 

        for val in vals:
            
            label     = [f'ind     {i+1}']
            loc       = 4
            ylim      = None
            unlogy    = False            
                        
            if versus=='r':
                x         = r
                xlabel    = r'$Radius \; [km]$'
                xlim      = [1e0,1e5]
                plot_type = 'loglog'
                unit      = 1#self.cm2km
            elif versus=='rho':
                if val in [versus, 'u1', 'sound']: continue
                x         = valmap['rho']
                xlabel    = r'Density $[g/cm^3]$'
                xlim      = [1e4,1e15]
                plot_type = 'loglog'
                unit      = 1#self.cm2km
            else: colored.error("unknown 'versus' {versus}, trying to exit")
                        
            if val in valmap.keys(): to_plot = np.array([[x*unit, valmap[val]]], dtype=object)
            else: to_plot = np.array([[x*unit, valmap.get(val, 'empty')]], dtype=object)
            
            if val == 'rho': 
                ylabel  = r'Density $[g/cm^3]$'
                ylim    = [1e4,1e15]
                loc     = 1
            elif val == 'u1':                
                ylabel  = r'Velocity_r $[cm/s]$'
                ylim    = [-1.5e10, 3e9]
                unlogy  = True        
            elif val == 'u2':                
                # print('%.2e, %.2e'%(np.amax(valmap[val]), np.amin(valmap[val])))
                ylabel  = r'Velocity_$\theta$ $[cm/s]$'
                ylim    = [-1e8, 1e8]
                unlogy  = True        
            elif val == 'u3':                
                ylabel  = r'Velocity_$\phi$ $[cm/s]$'
                ylim    = [-1e8, 1e8]
                unlogy  = True                        
            elif val == 'sound':                
                ylabel  = r'$V_{sound}$ $[cm/s]$'
                ylim    = [0, 1.4e10]
                loc     = 1
                unlogy  = True  
            elif val == 'mach':                
                ylabel  = 'Mach'
                ylim    = [3e-7,1.1e1]
                loc     = 4
            elif val == 'pressure':                
                ylabel  = r'$P_{gas} \; [\frac{g}{cm\;s^2}]$'
                ylim    = [1e20,1e36]
                loc     = 1
            elif val == 'pturb':                
                ylabel  = r'$P_{turb} \; [\frac{g}{cm\;s^2}]$'
                ylim    = [1e20,1e30]
                loc     = 1             
            elif val == 'pturb_pgas':
                ylabel  = r'$P_{turb}/P_{gas}$'
                ylim    = [1e-3,1e1]                
                loc     = 1
            elif val == 'vturb':                
                ylabel  = r'$Velocity_{turb} \; [cm/s]$'
                ylim    = [1e4,1e10]
                loc     = 2
            elif val == 'vturb2':              
                ylabel  = r'$Velocity_{turb}^2 \; [cm^2/s^2]$'
                ylim    = [1e8,1e20]
                loc     = 2                
            elif val == 'temperature':          
                to_plot = np.array([[x*unit, valmap[val]*1e10]], dtype=object)      
                ylabel  = r'Temperature $[K]$'
                ylim    = [1e7,4e11]
                loc     = 1
            elif val == 'encm':    
                to_plot = np.array([[x*unit, encm]], dtype=object)            
                ylabel  = r'Enclosed Mass $[M_{\odot}]$'
                ylim    = [1,2]
                unlogy    = True                
            elif val == 'ye':                
                ylabel  = r'$Y_e$'
                ylim    = [0,1]
                unlogy  = True 
            elif val == 'entropy':                
                ylabel  = r'Entropy $[k_b/baryon]$'
                ylim    = [1e-1, 2e1]
            elif val == 'abar':                
                ylabel  = r'$\bar{A}$'
                ylim    = [0,150]
                loc     = 1
                unlogy  = True
            elif val == 'u_int':                
                ylabel  = r'Energy $[erg/g]$'
                ylim    = [1e14,1e22]
            elif val == 'u_nu':
                if i < self.bounce_ind: continue
                to_plot = np.array([[x*unit, valmap.get('u_nue',  'empty')],
                                    [x*unit, valmap.get('u_nueb', 'empty')],
                                    [x*unit, valmap.get('u_nux',  'empty')]], dtype=object)
                ylabel  = r'Energy $\nu$ $[erg/g]$'
                ylim    = [1e8,1e22]
                label   = ['nue', 'nueb', 'nux']
            elif val == 'y_nu':                
                if i < self.bounce_ind: continue
                to_plot = np.array([[x*unit, valmap.get('y_nue',  'empty')],
                                    [x*unit, valmap.get('y_nueb', 'empty')],
                                    [x*unit, valmap.get('y_nux',  'empty')]], dtype=object)
                ylabel  = r'Fraction $\nu$'
                ylim    = [1e-10,1]
                label   = ['nue', 'nueb', 'nux']
            else:                 
                if self.rank==0 and i==self.interval[0]: 
                    colored.warn(f"no plotting parameters for val '{val}'; setting default")                
                ylabel  = val                
            
            if type(to_plot[-1][1]) != np.ndarray:
                if self.rank==0 and i==self.interval[0]: 
                    colored.warn(f"entries to plot '{val}' were not found; skipping")                        
                continue     
                                    
            if ylim!=None:                
                ymin = np.amin(to_plot[:,1])
                ymax = np.amax(to_plot[:,1])
                if (plot_type=="loglog" or plot_type=='semilogy') and ymin <= 0:
                    ymin = np.amin(np.absolute(to_plot[:,1]))
                    if ymin == 0: ymin = 1 # if ymin is still <=0 for log y-axis, set it to 1\
                while ymin < ylim[0]:ylim[0] *= 0.9
                while ymax > ylim[1]:ylim[1] *= 1.1
                                            
            if versus=='encm': loc = 0    
            
            if unlogy: 
                if   versus == 'r':    plot_type = 'semilogx'
                elif versus == 'encm': plot_type = 'plot'  
                
            if val=='pturb':      ylim = [1e20,1e30]
            if val=='pturb_pgas': ylim = [1e-3,1e1]
                     
            ax = line_plot(to_plot,
                           plot_type = plot_type,
                           label     = label,
                           linestyle = ['-','--',':'],               
                           figsize   = (10,6), 
                           dpi       = self.dpi
                           )                            
            
            # check if after bounce                
            if i >= self.bounce_ind:                
                if compute and vals.index(val)==0:
                    rt = ComputeRoutines(x, rho    = valmap['rho'], 
                                            v      = valmap['u1'], 
                                            vsound = valmap['sound'])
                                     
                    if self.dataset=='s12.0_g1.5k_c0.5k_p0.3k' and i<=650: self.old_shock_ind = -1
                    elif self.dataset=='s12.0_g9k_c8.4k_p_0.3k' and i<=670: self.old_shock_ind = -1
                    shock_ind, shock_x = rt.shock_radius(bump          = self.shock_region.get(i+1,0), 
                                                         old_shock_ind = self.old_shock_ind)
                    pns_ind,   pns_x   = rt.pns_radius(rho_threshold = rho_threshold)                                             
                    
                pns_edge    = x[int(pns_ind)]*unit
                shock_front = x[int(shock_ind)]*unit
                if   versus == 'r'   : line_label = '%.2e km'          
                elif versus == 'rho' : line_label = '%.2e $g/cm^3$'   
                elif versus == 'encm': line_label = '%.3f $M_{\odot}$'      
                         
                ax.axvline(x=pns_edge,linestyle='-',color='r',linewidth=1,
                           label=f'PNS    {line_label%pns_edge}')
                ax.axvline(x=shock_front,linestyle='--',color='r',linewidth=1,
                           label=f'shock {line_label%shock_front}')                
                            
            if self.only_post_bounce: ax.set_title('$t-t_{bounce}$ = %.2f ms'%((float(time1d)-float(bounce_time))*1e3))
            else: ax.set_title('$t$ = %.2f ms'%(float(time1d)*1e3))
                
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.set_xlim(xlim)            
            ax.set_ylim(ylim) 
            
            self.sim_label(ax)
            
            if versus == 'rho': ax.invert_xaxis()

            plt.legend(loc=loc)
            plt.tight_layout()
            if save_plot:        
                self.set_paths(val, versus)                
                plt.savefig(f'{self.plot_file}{self.save_name_amend}_{i+1}.png')
                
            if not show_plot: plt.close()
            
            # Get time evolution metrics
            if vals.index(val)==0:                
                
                if pns_x!=0:
                    self.pns_ind_ar[i]    = pns_ind
                    self.pns_x_ar[i]      = pns_x
                    # self.pns_encm_ar[i]   = encm[pns_ind]                
                    self.shock_ind_ar[i]  = shock_ind
                    self.shock_x_ar[i]    = shock_x
                    # self.shock_encm_ar[i] = encm[shock_ind]
                    self.time_ar[i]       = time1d   
                    
                    self.old_shock_ind    = shock_ind                                                              
                
                # # Find mass shell indexes (initializes only once)
                # if self.shell_ar.size == 0: 
                #     shell_old        = 0
                #     shell_counter    = 0 
                #     shells_after     = 1.1 #M_sol                                                          
                #     shell_counts     = int((encm[-1]-shells_after)//self.delta_shell)
                #     self.shell_ar    = np.zeros((self.numfiles,shell_counts))
                #     self.shell_index = np.zeros(shell_counts, dtype=int)
                                        
                #     for shell_i in range(len(encm)):
                #         shell = encm[shell_i]                    
                #         if shell >= shells_after and (shell-shell_old) >= self.delta_shell:
                #             self.shell_index[shell_counter] = shell_i
                #             shell_counter += 1
                #             shell_old      = shell
                    
                #     while shell_counter < self.shell_ar.shape[-1]:
                #         self.shell_ar    = np.delete(self.shell_ar,    -1, axis=1)
                #         self.shell_index = np.delete(self.shell_index, -1, axis=0)               

                # # Track mass shell positions at time index i
                # for j,shell_i in enumerate(self.shell_index):     
                #     self.shell_ar[i,j] = r[shell_i]
            
            done=True if (i==self.numfiles and vals.index(val)==(len(vals)-1)) else False
            if self.rank == 0: self.progress_bar(i+1, val, done = done)          
        return
    
    def movie(self, val, versus='r', fps=15, start=1, printout=False):      
        
        self.set_paths(val,versus)
        if len(os.listdir(self.plot_path)) == 0: return # if dir is empty
        
        padding_val = int(12-len(val)) * ' '
        
        if self.only_post_bounce:
            name_amend = '_bounce'
            start      = self.bounce_ind
        else: name_amend = ''
            
        name = f'{self.plot_file}{self.save_name_amend}'
        
        movie_name = f'{self.movie_save_path}{val}{self.versus_name}{self.save_name_amend}'                        
        result = Popen((f'ffmpeg -r {fps} -start_number {start} -i {name}_%d.png'+
                        f' -vcodec libx264 {movie_name}{name_amend}.mp4 -y'),
                        shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)           
        output, error = result.communicate()   
        
        if printout: print(output, error)  
        
        print(f'{val}{padding_val}: {val}{self.versus_name}{self.save_name_amend}{name_amend}.mp4')
        
        return            
    
class colored:
    RED    = '\033[31m'
    GREEN  = '\033[32m'
    YELLOW = '\033[33m'
    ORANGE = '\033[34m'
    PURPLE = '\033[35m' 
    CYAN   = "\033[36m"
    RESET  = "\033[0m"
    
    @classmethod
    def head(cls, message): print(cls.CYAN+f"{message}"+cls.RESET) 
    
    @classmethod
    def subhead(cls, message): print(cls.PURPLE+f"{message}"+cls.RESET)   
    
    @classmethod
    def warn(cls, message): print(cls.YELLOW+f"WARNING: {message}"+"\033[K"+cls.RESET)

    @classmethod        
    def error(cls, message): sys.exit(cls.RED+f"ERROR: {message}"+"\033[K"+cls.RESET)    
    
if __name__=='__main__':
    main()
