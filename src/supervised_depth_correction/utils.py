import cv2
import gradslam
import open3d as o3d
import matplotlib.pyplot as plt
import torch
import os
from scipy import interpolate
import numpy as np
from .models import SparseConvNet
from PIL import Image


def load_model(path=None):
    model = SparseConvNet()
    if path:
        if os.path.exists(path):
            print('Loading model weights from %s' % path)
            model.load_state_dict(torch.load(path, map_location='cpu'))
        else:
            print('No model weights found!!!')
    return model


def plot_depth(depth_sparse, depth_pred, depth_gt, episode, mode, visualize=False, log_dir=None):
    # convert depth into np images
    depth_img_gt_np = depth_gt.detach().cpu().numpy().squeeze()
    depth_img_sparse_np = depth_sparse.detach().cpu().numpy().squeeze()
    pred_np = depth_pred.detach().cpu().numpy().squeeze()

    # plot images
    fig = plt.figure()
    ax = fig.add_subplot(3, 1, 1)
    plt.imshow(depth_img_sparse_np)
    ax.set_title('Sparse')
    ax = fig.add_subplot(3, 1, 2)
    plt.imshow(pred_np)
    ax.set_title('Prediction')
    ax = fig.add_subplot(3, 1, 3)
    plt.imshow(depth_img_gt_np)
    ax.set_title('Ground truth')
    fig.tight_layout(h_pad=1)
    if log_dir is not None:
        plt.savefig(os.path.join(log_dir, f'plot-{mode}-{episode}.png'))
    if visualize:
        plt.show()
    plt.close(fig)


def plot_pc(pc, episode, mode, visualize=False, log_dir=None):
    """
    Args:
        pc: <gradslam.Pointclouds> or <torch.Tensor>
    """
    if isinstance(pc, gradslam.Pointclouds):
        pcd = pc.open3d(0)
    elif isinstance(pc, torch.Tensor):
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pc.detach().cpu().view(-1, 3))
    else:
        raise ValueError('Input should be gradslam.Pointclouds or torch.Tensor')
    # Flip it, otherwise the point cloud will be upside down
    pcd.transform([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
    if log_dir is not None:
        o3d.io.write_point_cloud(os.path.join(log_dir, f'map-{mode}-{episode}.pcd'), pcd)
    if visualize:
        o3d.visualization.draw_geometries([pcd])


def plot_metric(metric, metric_title, visualize=False, log_dir=None, val_scaling=None):
    """
    Plots graph of metric over episodes
    Args:
        metric: list of <torch.tensor>
        metric_title: string
    """
    fig = plt.figure()
    if val_scaling is None:
        x_ax = [i for i in range(len(metric))]
    else:
        x_ax = [i*val_scaling for i in range(len(metric))]
    y_ax = [loss.detach().cpu().numpy() for loss in metric]
    plt.plot(x_ax, y_ax)
    plt.xlabel('Episode')
    plt.ylabel(metric_title)
    plt.title(f'{metric_title} over episodes')
    if log_dir is not None:
        plt.savefig(os.path.join(log_dir, f'{metric_title}.png'))
    if visualize:
        plt.show()
    plt.close(fig)


def interpolate_missing_pixels(
        image: np.ndarray,
        mask: np.ndarray,
        method: str = 'nearest',
        fill_value: float = 0
):
    """
    :param image: a 2D image
    :param mask: a 2D boolean image, True indicates missing values
    :param method: interpolation method, one of
        'nearest', 'linear', 'cubic'.
    :param fill_value: which value to use for filling up data outside the
        convex hull of known pixel values.
        Default is 0, Has no effect for 'nearest'.
    :return: the image with missing values interpolated
    """

    h, w = image.shape[:2]
    xx, yy = np.meshgrid(np.arange(w), np.arange(h))

    known_x = xx[~mask]
    known_y = yy[~mask]
    known_v = image[~mask]
    missing_x = xx[mask]
    missing_y = yy[mask]

    interp_values = interpolate.griddata(
        (known_x, known_y), known_v, (missing_x, missing_y),
        method=method, fill_value=fill_value
    )

    interp_image = image.copy()
    interp_image[missing_y, missing_x] = interp_values

    return interp_image


def save_gradslam_image(img, img_path):
    """
    Save depth image from
    :param img_torch: <torch.tensor> of shape (B, S, H, W, CH)
    """
    img = torch.squeeze(img, 0)
    img = torch.squeeze(img, 0)
    img = img.cpu().detach().numpy()
    img *= (2 ** 8)     # shift values range
    data_pil = Image.fromarray(np.squeeze(img.astype(np.uint16)), mode='I;16').convert(mode='I')
    data_pil.save(img_path)


def convert_img_label(name):
    default = "0000000000"
    name = str(name)
    return default[:-len(name)] + name


def complete_sequence(model, dataset, path_to_save, subseq):
    """
    Runs depth images through the model and saves them as a KITTI compatible sequence
    :param path_to_save: path to KITTI depth files (e.g. KITTI/depth/train)
    """
    subfolders = [subseq, "proj_depth", "prediction", "image_02"]
    for subfold in subfolders:
        path_to_save = os.path.join(path_to_save, subfold)
        if not os.path.isdir(path_to_save):
            os.mkdir(path_to_save)

    for i in dataset.ids:
        img_name = convert_img_label(i) + ".png"
        img_path = os.path.join(path_to_save, img_name)
        if os.path.exists(img_path):
            continue
        colors, depths, intrinsics, poses = dataset[i]
        mask = (depths > 0).float()
        pred = model(depths, mask)
        save_gradslam_image(pred, img_path)
