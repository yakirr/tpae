import matplotlib.pyplot as plt
import numpy as np
from minisom import MiniSom
from sklearn.preprocessing import scale
import cv2
import torch
import xarray as xr
import seaborn as sns
import pandas as pd
from .data import samples as tds

def plot_with_reconstruction(model, examples, show=True, channels=[0,1,2], pmin=None, pmax=None, cmap='seismic'):
    examples = (examples[0].permute(0,3,1,2), examples[1])
    model.eval()
    with torch.no_grad():
        predictions, means, _ = model.forward(examples)
    examples = examples[0].permute(0,2,3,1).cpu().numpy()
    predictions = predictions.permute(0,2,3,1).cpu().numpy()
    losses = np.mean((examples - predictions)**2, axis=(1,2,3))

    fig = plt.figure(figsize=(32,len(channels)*4))
    for j, channel in enumerate(channels):
        for i, (a, b) in enumerate(zip(predictions, examples)):
            plt.subplot(2*len(channels), len(examples), len(examples)*(2*j) + i + 1)
            plt.imshow(b[:,:,channel], vmin=pmin[channel], vmax=pmax[channel], cmap=cmap)
            plt.axis('off')
            if j == 0:
                plt.text(20, 1, f'{losses[i]:.2f}', ha='center', va='bottom', fontsize=16)
            plt.subplot(2*len(channels), len(examples), len(examples)*(2*j+1) + i + 1)
            plt.imshow(a[:,:,channel], vmin=pmin[channel], vmax=pmax[channel], cmap=cmap)
            plt.axis('off')

    if show:
        plt.tight_layout()
        plt.show()

def plot_patches_separatechannels(examples, choose=None, vmax=10, vmin=None, channels=[0,1,2], channelnames=None):
    if choose is not None:
        examples = examples[np.random.choice(range(len(examples)), size=min(choose, len(examples)), replace=False)]
    if vmin is None:
        vmin = -vmax
    if isinstance(vmax, (int, float, str)):
        vmax = [vmax] * len(channels)
        vmin = [vmin] * len(channels)
    
    fig = plt.figure(figsize=(len(examples)*1.5, len(channels)*1.5))
    for j, channel in enumerate(channels):
        for i, a in enumerate(examples):
            plt.subplot(len(channels), len(examples), i + j*len(examples) + 1)
            plt.imshow(a[:,:,channel], vmin=vmin[channel], vmax=vmax[channel], cmap='seismic')
            plt.axis('off')
            if channelnames is not None and i == 0:
                plt.gca().text(-5, 20, channelnames[j], va='center', ha='right', rotation=90)

    plt.tight_layout()
    plt.show()

def scaler(minimum=0, maximum=255):
    def rescale(x):
        return np.minimum(np.maximum((x - minimum) / (maximum - minimum), 0), 1)
    return rescale

def apply_colormap(pieces, colormaps):
    if len(pieces.shape) == 3:
        pieces = np.array([pieces])
        reshape = True
    else:
        reshape = False
    images = np.zeros((pieces.shape[0], pieces.shape[1], pieces.shape[2], 3))
    for [channel, color, scaler] in colormaps:
        images += (scaler(pieces[:,:,:,channel])[:,:,:,None] * np.array(color)[None,None,None,:])
    images[images > 1] = 1

    if reshape:
        images = images[0]

    return images

# colormaps consists of tuples of the form [channel, color, scaler]
def plot_patches_overlaychannels(examples, colormaps, nx=5, ny=5, show=True, seed=None):
    if nx*ny < len(examples):
        if seed is not None: np.random.seed(seed)
        ix = np.random.choice(range(len(examples)), size=nx*ny, replace=False)
        examples = examples[ix]
    else:
        ix = range(len(examples))

    images = apply_colormap(examples, colormaps)
    
    fig = plt.figure(figsize=(nx,ny))
    for i, a in enumerate(images):
        plt.subplot(ny,nx,i+1)
        plt.imshow(a)
        plt.axis('off')
    plt.tight_layout()
    if show:
        plt.show()
    return ix

# colormaps consists of tuples of the form [channel, color, scaler]
def plot_patches_overlaychannels_som(examples, latent, colormaps, nx=5, ny=5, show=True, seed=None, scale_factor=1, spacing=None,
        subsamplefactor=None):
    if seed is not None: np.random.seed(seed)
    if subsamplefactor is not None:
        ix = np.random.choice(range(len(examples)), size=int(subsamplefactor*nx*ny), replace=False)
        examples = examples[ix]
        latent = latent[ix]

    som = MiniSom(nx, ny, len(latent[0]),
              neighborhood_function='gaussian', sigma=1.5,
              random_seed=1)
    latent = scale(latent)
    som.pca_weights_init(latent)
    som.train_random(latent, 1000, verbose=False)
    map = som.labels_map(latent, range(len(latent)))
    
    fig, axs = plt.subplots(nx, ny,
        figsize=(scale_factor*nx,scale_factor*ny))
    for p, box in map.items():
        box = list(box)
        c = np.random.choice(box, size=1)[0]
        image = apply_colormap(examples[c], colormaps)
        ax = axs[p[0],p[1]]
        ax.imshow(image)
    for ax in axs.flatten():
        ax.axis('off')
        
    if spacing is None:
        plt.tight_layout()
    else:
        spacing *= scale_factor
        plt.subplots_adjust(left=spacing/2, right=1-spacing/2, top=1-spacing/2, bottom=spacing/2, wspace=spacing, hspace=spacing)
    
    if show:
        plt.show()

def plot_patches_overlaychannels_sorted(examples, colormaps, labels=None, nx=5, ny=5, show=True):
    images = apply_colormap(examples, colormaps)
    
    fig, axs = plt.subplots(nx, ny, figsize=(nx,ny))
    for i, a in enumerate(images[:nx*ny]):
        plt.subplot(ny,nx,i+1)
        plt.imshow(a)
        if labels is not None:
            plt.text(2, 10, f'{labels[i]}', color='white')
        plt.axis('off')
    plt.tight_layout()
    if show:
        plt.show()

# each color channel should be a tuple of the form (channel, scaler)
def plot_patches_fourcolors(examples, nx=5, ny=5,
            red=(None, None), cyan=(None, None), green=(None, None), yellow=(None, None), show=True):
    colormaps = []
    
    if red[0] is not None:
        colormaps.append([red[0], [1,0,0], red[1]])
    if green[0] is not None:
        colormaps.append([green[0], [0,1,0], green[1]])
    if cyan[0] is not None:
        colormaps.append([cyan[0], [0,1,1], cyan[1]])
    if yellow[0] is not None:
        colormaps.append([yellow[0], [1,1,0], yellow[1]])

    plot_patches_overlaychannels(examples, colormaps, nx=nx, ny=ny, show=show)

def diff_markers(patch_avgs, pos_set, neg_set, markernames, labels=['T','F'], nmarkers=10, ascending=False, show=True):
    marker_diffs = pd.DataFrame(index=markernames, columns=['diff'])
    for m in markernames:
        marker_diffs.loc[m, 'diff'] = patch_avgs.loc[pos_set, m].median() -  patch_avgs.loc[neg_set, m].median()
    marker_diffs = marker_diffs.sort_values(by='diff', ascending=ascending)
    
    df = pd.melt(patch_avgs, value_vars=marker_diffs[:nmarkers].index.values,
                 var_name='marker', value_name='value', ignore_index=False)
    df.loc[pos_set, 'status'] = labels[0]
    df.loc[neg_set, 'status'] = labels[1]
    sns.violinplot(data=df, x='marker', y='value', hue='status')
    plt.ylabel('level')
    if show:
        plt.show()

    return marker_diffs[:nmarkers].index.values, marker_diffs.iloc[-nmarkers:].index.values

def spatialplot(samples, sortkey, allpatches, scores, rgbs=[[1.,0.,0.]],
        labels=None,
        highlight=None, outline_rgba=[0.,1.,0.,1.], outline_thickness=10,
        skipthresh=10, skipevery=1, stopafter=None,
        vmax=1, ncols=5, size=2, filterempty=False, show=True):
    toplot = allpatches.sid.value_counts() > skipthresh
    nsamples = toplot.sum() // skipevery
    nrows = int(np.ceil(nsamples/ncols))
    fig, axs = plt.subplots(nrows=nrows, ncols=ncols,
                            figsize=(ncols*size,nrows*size))

    for ax, sid in zip(axs.flatten(), sortkey[toplot].sort_values().index[::skipevery]):
        print('.', end='')
        mypatches = allpatches[allpatches.sid == sid]
        if len(mypatches) < skipthresh:
            continue

        canvas = tds.union_patches_in_sample(mypatches, samples[sid])
        if filterempty:
            indices = np.where(canvas)
            nonempty_rows = canvas.sum(axis=1) > 0
            nonempty_cols = canvas.sum(axis=0) > 0
        else:
            nonempty_rows = range(len(canvas))
            nonempty_cols = range(len(canvas[0]))

        ax.imshow(canvas[nonempty_rows][:,nonempty_cols], cmap='grey')
        for score, color in zip(scores, rgbs):
            sigcanvas = np.zeros((*canvas.shape, 4))
            sigcanvas[:,:,:3] = color
            
            score_ = score[mypatches.index].values / vmax
            for (x,y,ps), s in zip(mypatches[['x','y','patchsize']].values, score_):
                x,y,ps = int(x), int(y), int(ps)
                sigcanvas[y:y+ps,x:x+ps,-1] += s
            sigcanvas[sigcanvas > 1] = 1
            ax.imshow(sigcanvas[nonempty_rows][:,nonempty_cols])

        if highlight is not None:
            myhighlight = highlight[mypatches.index]
            mask = tds.union_patches_in_sample(mypatches[myhighlight != 0], samples[sid])
            boundary = tds.get_boundary(mask.data, outline_rgba, thickness=outline_thickness)
            ax.imshow(boundary[nonempty_rows][:,nonempty_cols])
        if labels is not None:
            ax.set_title(labels[sid], color='white', fontsize=12)

        if stopafter is not None and ax == axs.flatten()[stopafter-1]:
            break

    for ax in axs.flatten()[nsamples:]:
        ax.imshow(np.zeros((10,10)), cmap='grey', vmin=0, vmax=1)

    for ax in axs.flatten():
        ax.spines['top'].set_color('white')
        ax.spines['bottom'].set_color('white')
        ax.spines['left'].set_color('white')
        ax.spines['right'].set_color('white')
        ax.set_xticks([])
        ax.set_yticks([])
        ax.xaxis.set_tick_params(length=0)
        ax.yaxis.set_tick_params(length=0)
        ax.set_xticklabels([])
        ax.set_yticklabels([])

            
    fig.patch.set_facecolor('black')

    if show:
        plt.show()