import numpy as np
import torch
from torch import nn, Tensor
from torch.utils.data import Dataset, DataLoader
from torch.optim.lr_scheduler import LRScheduler
import torch.nn.functional as F
import time
import pandas as pd
import os
from tempfile import TemporaryDirectory

class CVAE(nn.Module):
    """Convolutional variational autoencoder."""

    def __init__(self, ncolors : int, patch_size : int,
            latent_dim: int=100, nfilters1: int=256, nfilters2: int=512,
            ignore_empty: bool=True):
        super().__init__()
        self.latent_dim = latent_dim
        self.nfilters1 = nfilters1
        self.nfilters2 = nfilters2
        self.ignore_empty = ignore_empty
        
        self.encoder = nn.Sequential(
            nn.Conv2d(ncolors, self.nfilters1, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(self.nfilters1, self.nfilters2, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        self.encoder_end = nn.Linear((patch_size//4)*(patch_size//4)*self.nfilters2 + ncolors, latent_dim + latent_dim)
        
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, (patch_size//4)*(patch_size//4)*self.nfilters2),
            nn.Unflatten(1, (self.nfilters2, patch_size//4, patch_size//4)),
            nn.ReLU(),
            nn.ConvTranspose2d(self.nfilters2, self.nfilters1, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.ReLU(),
            nn.ConvTranspose2d(self.nfilters1, ncolors, kernel_size=3, stride=2, padding=1, output_padding=1),
        )

    def encode(self, x : Tensor):
        output = self.encoder(x)
        avg_profile = x.mean(axis=(2,3))
        output = self.encoder_end(torch.cat((output, avg_profile), dim=1))
        mean, logvar = torch.split(output, self.latent_dim, dim=1)
        return mean, logvar

    def reparameterize(self, mean : Tensor, logvar : Tensor):
        eps = torch.randn_like(mean)
        return eps * torch.exp(logvar * .5) + mean

    def decode(self, z : Tensor):
        return self.decoder(z)

def reconstruction_loss(x_true : Tensor, x_pred : Tensor, ignore_empty: bool, per_sample: bool=False):
    if ignore_empty:
        mask = x_true[:,-1,:,:].to(torch.bool)
    else:
        mask = torch.ones((x_true.shape[0], x_true.shape[2], x_true.shape[3]), dtype=torch.bool)

    mask = mask.unsqueeze(1).expand(-1, x_true.shape[1], -1, -1)
    sse = torch.sum((x_pred*mask - x_true*mask)**2, dim=(1,2,3))
    sse /= torch.sum(mask, dim=(1,2,3))
    # sse = torch.sum((x_pred[mask] - x_true)**2, dim=(1,2,3))
    
    if per_sample:
        return sse
    else:
        return torch.mean(sse)

def kl_loss(mean : Tensor, logvar : Tensor):
    return -0.5 * torch.mean(
        torch.sum(1 + logvar - mean.pow(2) - logvar.exp(),
        dim=1))

def per_batch_logging(model : nn.Module, batch_num : int, rlosses : list, vaelosses : list,
        kl_weight : float, log_interval : int, scheduler : LRScheduler):
    lr = scheduler.get_last_lr()[0]
    cur_rloss = np.mean(rlosses[-log_interval:])
    cur_vaeloss = np.mean(vaelosses[-log_interval:])

    print(f'batch {batch_num:5d} | '
            f'lr {lr:.2g} | '
            f'r-loss {cur_rloss:.2f} | '
            f'vae-loss {cur_vaeloss:.2f} | '
            f'kl-weight {kl_weight}')

def train_one_epoch(model : nn.Module, train_dataset : Dataset,
        optimizer : torch.optim.Optimizer, scheduler : LRScheduler,
        batch_size : int, log_interval : int=20, kl_weight : float=1,
        per_batch_logging=per_batch_logging):
    model.train()
    train_loader = DataLoader(
        dataset=train_dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=torch.Generator(device=torch.get_default_device()))
    print(f'#batches: {len(train_loader)}')

    losses = []; vaelosses = []; rlosses = []
    for n, batch in enumerate(train_loader):
        # Forward pass
        mean, logvar = model.encode(batch)
        z = model.reparameterize(mean, logvar)
        predictions = model.decode(z)

        rloss = reconstruction_loss(batch, predictions, model.ignore_empty)
        vaeloss = kl_weight * kl_loss(mean, logvar)
        loss = vaeloss + rloss

        # Backward pass
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
        optimizer.step()

        # Save info
        losses.append(float(loss))
        rlosses.append(float(rloss))
        vaelosses.append(float(vaeloss))

        # Log
        if n % log_interval == 0 and n > 0:
            per_batch_logging(model, n, rlosses, vaelosses, kl_weight, log_interval, scheduler)

    return pd.DataFrame({'loss':losses, 'rloss':rlosses, 'vaeloss':vaelosses, 'kl_weight':kl_weight})

def evaluate(model : nn.Module, eval_dataset : Dataset, batch_size : int=1000,
        detailed : bool=False):
    model.eval()
    eval_loader = DataLoader(
        dataset=eval_dataset,
        batch_size=batch_size,
        shuffle=False)

    rlosses = []; embeddings = []
    with torch.no_grad():
        for n, batch in enumerate(eval_loader):
            print('.', end='')
            mean, _ = model.encode(batch)
            predictions = model.decode(mean)

            rlosses.append(
                reconstruction_loss(batch, predictions, model.ignore_empty, per_sample=True).detach().cpu().numpy()
                )
            if detailed: embeddings.append(mean.detach().cpu().numpy())

    if detailed:
        return np.concatenate(rlosses), np.concatenate(embeddings)
    else:
        return np.concatenate(rlosses).mean()

def simple_per_epoch_logging(model, epoch, epoch_start_time, rlosses, losslog):
    print(f'end of epoch {epoch}: avg val loss = {rlosses.mean()}')

def full_training(model : nn.Module, train_dataset : Dataset,
        val_dataset : Dataset, optimizer : torch.optim.Optimizer,
        scheduler : LRScheduler, batch_size : int=128, n_epochs : int=10,
        kl_weight : float=1, per_epoch_logging=simple_per_epoch_logging,
        per_batch_logging=per_batch_logging):
    best_val_loss = float('inf')
    losslogs = []

    with TemporaryDirectory() as tempdir:
        best_model_params_path = os.path.join(tempdir, "best_model_params.pt")

        for epoch in range(1, n_epochs + 1):
            epoch_start_time = time.time()
            losslog = train_one_epoch(
                model, train_dataset, optimizer, scheduler, batch_size, kl_weight=kl_weight,
                per_batch_logging=per_batch_logging)
            rlosses, _ = evaluate(model, val_dataset, detailed=True)
            scheduler.step()

            losslog['val_rloss'] = np.NaN
            losslog.val_rloss.values[-1] = rlosses.mean()
            losslogs.append(losslog)
            losslogs_sofar = pd.concat(losslogs, axis=0).reset_index(drop=True)

            per_epoch_logging(model, epoch, epoch_start_time, rlosses,
                losslogs_sofar)

            if rlosses.mean() < best_val_loss:
                best_val_loss = rlosses.mean()
                torch.save(model.state_dict(), best_model_params_path)

        model.load_state_dict(torch.load(best_model_params_path)) # load best model states
    return model, losslogs_sofar