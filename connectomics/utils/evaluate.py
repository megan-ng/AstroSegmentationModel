import os
import numpy as np
import scipy.sparse as sparse
import h5py
from scipy import ndimage
import tifffile
__all__ = [
    'get_binary_jaccard',
]


def adapted_rand(seg, gt, all_stats=False):
    """Compute Adapted Rand error as defined by the SNEMI3D contest [1]

    Formula is given as 1 - the maximal F-score of the Rand index 
    (excluding the zero component of the original labels). Adapted 
    from the SNEMI3D MATLAB script, hence the strange style.

    Parameters
    ----------
    seg : np.ndarray
        the segmentation to score, where each value is the label at that point
    gt : np.ndarray, same shape as seg
        the groundtruth to score against, where each value is a label
    all_stats : boolean, optional
        whether to also return precision and recall as a 3-tuple with rand_error

    Returns
    -------
    are : float
        The adapted Rand error; equal to $1 - \frac{2pr}{p + r}$,
        where $p$ and $r$ are the precision and recall described below.
    prec : float, optional
        The adapted Rand precision. (Only returned when `all_stats` is ``True``.)
    rec : float, optional
        The adapted Rand recall.  (Only returned when `all_stats` is ``True``.)

    References
    ----------
    [1]: http://brainiac2.mit.edu/SNEMI3D/evaluation
    I think that;s how they compute for the 
    https://stackoverflow.com/questions/37411370/computing-rand-error-efficiently
    """
    # segA is truth, segB is query
    segA = np.ravel(gt) #unrolls to 1D array 
    segB = np.ravel(seg) #unrolls to 1D array ``
    n = segA.size #shape of the array 

    n_labels_A = np.amax(segA) + 1 # maximum of an array + 1 to account for the new label
    n_labels_B = np.amax(segB) + 1 # maximum of an array + 1 to account for the new label

    ones_data = np.ones(n, int)

    p_ij = sparse.csr_matrix(
        (ones_data, (segA[:], segB[:])), shape=(n_labels_A, n_labels_B))

    a = p_ij[1:n_labels_A, :]
    b = p_ij[1:n_labels_A, 1:n_labels_B]
    c = p_ij[1:n_labels_A, 0].todense()
    d = b.multiply(b)

    a_i = np.array(a.sum(1))
    b_i = np.array(b.sum(0))

    sumA = np.sum(a_i * a_i)
    sumB = np.sum(b_i * b_i) + (np.sum(c) / n)
    sumAB = np.sum(d) + (np.sum(c) / n)

    precision = sumAB / sumB
    recall = sumAB / sumA

    fScore = 2.0 * precision * recall / (precision + recall)
    are = 1.0 - fScore

    if all_stats:
        return (are, precision, recall)
    else:
        return are

# Evaluation code courtesy of Juan Nunez-Iglesias, taken from
# https://github.com/janelia-flyem/gala/blob/master/gala/evaluate.py


def voi(reconstruction, groundtruth, ignore_reconstruction=[], ignore_groundtruth=[0]):
    """Return the conditional entropies of the variation of information metric. [1]

    Let X be a reconstruction, and Y a ground truth labelling. The variation of 
    information between the two is the sum of two conditional entropies:

        VI(X, Y) = H(X|Y) + H(Y|X).

    The first one, H(X|Y), is a measure of oversegmentation, the second one, 
    H(Y|X), a measure of undersegmentation. These measures are referred to as 
    the variation of information split or merge error, respectively.

    Parameters
    ----------
    seg : np.ndarray, int type, arbitrary shape
        A candidate segmentation.
    gt : np.ndarray, int type, same shape as `seg`
        The ground truth segmentation.
    ignore_seg, ignore_gt : list of int, optional
        Any points having a label in this list are ignored in the evaluation.
        By default, only the label 0 in the ground truth will be ignored.

    Returns
    -------
    (split, merge) : float
        The variation of information split and merge error, i.e., H(X|Y) and H(Y|X)

    References
    ----------
    [1] Meila, M. (2007). Comparing clusterings - an information based 
    distance. Journal of Multivariate Analysis 98, 873-895.
    """
    (hyxg, hxgy) = split_vi(reconstruction, groundtruth,
                            ignore_reconstruction, ignore_groundtruth)
    return (hxgy, hyxg)


def split_vi(x, y=None, ignore_x=[0], ignore_y=[0]):
    """Return the symmetric conditional entropies associated with the VI.

    The variation of information is defined as VI(X,Y) = H(X|Y) + H(Y|X).
    If Y is the ground-truth segmentation, then H(Y|X) can be interpreted
    as the amount of under-segmentation of Y and H(X|Y) is then the amount
    of over-segmentation.  In other words, a perfect over-segmentation
    will have H(Y|X)=0 and a perfect under-segmentation will have H(X|Y)=0.

    If y is None, x is assumed to be a contingency table.

    Parameters
    ----------
    x : np.ndarray
        Label field (int type) or contingency table (float). `x` is
        interpreted as a contingency table (summing to 1.0) if and only if `y`
        is not provided.
    y : np.ndarray of int, same shape as x, optional
        A label field to compare to `x`.
    ignore_x, ignore_y : list of int, optional
        Any points having a label in this list are ignored in the evaluation.
        Ignore 0-labeled points by default.

    Returns
    -------
    sv : np.ndarray of float, shape (2,)
        The conditional entropies of Y|X and X|Y.

    See Also
    --------
    vi
    """
    _, _, _, hxgy, hygx, _, _ = vi_tables(x, y, ignore_x, ignore_y)
    # false merges, false splits
    return np.array([hygx.sum(), hxgy.sum()])


def vi_tables(x, y=None, ignore_x=[0], ignore_y=[0]):
    """Return probability tables used for calculating VI.

    If y is None, x is assumed to be a contingency table.

    Parameters
    ----------
    x, y : np.ndarray
        Either x and y are provided as equal-shaped np.ndarray label fields
        (int type), or y is not provided and x is a contingency table
        (sparse.csc_matrix) that may or may not sum to 1.
    ignore_x, ignore_y : list of int, optional
        Rows and columns (respectively) to ignore in the contingency table.
        These are labels that are not counted when evaluating VI.

    Returns
    -------
    pxy : sparse.csc_matrix of float
        The normalized contingency table.
    px, py, hxgy, hygx, lpygx, lpxgy : np.ndarray of float
        The proportions of each label in `x` and `y` (`px`, `py`), the
        per-segment conditional entropies of `x` given `y` and vice-versa, the
        per-segment conditional probability p log p.
    """
    if y is not None:
        pxy = contingency_table(x, y, ignore_x, ignore_y)
    else:
        cont = x
        total = float(cont.sum())
        # normalize, since it is an identity op if already done
        pxy = cont / total

    # Calculate probabilities
    px = np.array(pxy.sum(axis=1)).ravel()
    py = np.array(pxy.sum(axis=0)).ravel()
    # Remove zero rows/cols
    nzx = px.nonzero()[0]
    nzy = py.nonzero()[0]
    nzpx = px[nzx]
    nzpy = py[nzy]
    nzpxy = pxy[nzx, :][:, nzy]

    # Calculate log conditional probabilities and entropies
    lpygx = np.zeros(np.shape(px))
    lpygx[nzx] = xlogx(divide_rows(nzpxy, nzpx)).sum(axis=1).ravel()
    # \sum_x{p_{y|x} \log{p_{y|x}}}
    hygx = -(px*lpygx)  # \sum_x{p_x H(Y|X=x)} = H(Y|X)

    lpxgy = np.zeros(np.shape(py))
    lpxgy[nzy] = xlogx(divide_columns(nzpxy, nzpy)).sum(axis=0).ravel()
    hxgy = -(py*lpxgy)

    return [pxy] + list(map(np.asarray, [px, py, hxgy, hygx, lpygx, lpxgy]))


def contingency_table(seg, gt, ignore_seg=[0], ignore_gt=[0], norm=True):
    """Return the contingency table for all regions in matched segmentations.

    Parameters
    ----------
    seg : np.ndarray, int type, arbitrary shape
        A candidate segmentation.
    gt : np.ndarray, int type, same shape as `seg`
        The ground truth segmentation.
    ignore_seg : list of int, optional
        Values to ignore in `seg`. Voxels in `seg` having a value in this list
        will not contribute to the contingency table. (default: [0])
    ignore_gt : list of int, optional
        Values to ignore in `gt`. Voxels in `gt` having a value in this list
        will not contribute to the contingency table. (default: [0])
    norm : bool, optional
        Whether to normalize the table so that it sums to 1.

    Returns
    -------
    cont : scipy.sparse.csc_matrix
        A contingency table. `cont[i, j]` will equal the number of voxels
        labeled `i` in `seg` and `j` in `gt`. (Or the proportion of such voxels
        if `norm=True`.)
    """
    segr = seg.ravel()
    gtr = gt.ravel()
    ignored = np.zeros(segr.shape).astype(bool)
    data = np.ones(len(gtr))
    for i in ignore_seg:
        ignored[segr == i] = True
    for j in ignore_gt:
        ignored[gtr == j] = True
    data[ignored] = 0
    cont = sparse.coo_matrix((data, (segr, gtr))).tocsc()
    if norm:
        cont /= float(cont.sum())
    return cont


def divide_columns(matrix, row, in_place=False):
    """Divide each column of `matrix` by the corresponding element in `row`.

    The result is as follows: out[i, j] = matrix[i, j] / row[j]

    Parameters
    ----------
    matrix : np.ndarray, scipy.sparse.csc_matrix or csr_matrix, shape (M, N)
        The input matrix.
    column : a 1D np.ndarray, shape (N,)
        The row dividing `matrix`.
    in_place : bool (optional, default False)
        Do the computation in-place.

    Returns
    -------
    out : same type as `matrix`
        The result of the row-wise division.
    """
    if in_place:
        out = matrix
    else:
        out = matrix.copy()
    if type(out) in [sparse.csc_matrix, sparse.csr_matrix]:
        if type(out) == sparse.csc_matrix:
            convert_to_csc = True
            out = out.tocsr()
        else:
            convert_to_csc = False
        row_repeated = np.take(row, out.indices)
        nz = out.data.nonzero()
        out.data[nz] /= row_repeated[nz]
        if convert_to_csc:
            out = out.tocsc()
    else:
        out /= row[np.newaxis, :]
    return out


def divide_rows(matrix, column, in_place=False):
    """Divide each row of `matrix` by the corresponding element in `column`.

    The result is as follows: out[i, j] = matrix[i, j] / column[i]

    Parameters
    ----------
    matrix : np.ndarray, scipy.sparse.csc_matrix or csr_matrix, shape (M, N)
        The input matrix.
    column : a 1D np.ndarray, shape (M,)
        The column dividing `matrix`.
    in_place : bool (optional, default False)
        Do the computation in-place.

    Returns
    -------
    out : same type as `matrix`
        The result of the row-wise division.
    """
    if in_place:
        out = matrix
    else:
        out = matrix.copy()
    if type(out) in [sparse.csc_matrix, sparse.csr_matrix]:
        if type(out) == sparse.csr_matrix:
            convert_to_csr = True
            out = out.tocsc()
        else:
            convert_to_csr = False
        column_repeated = np.take(column, out.indices)
        nz = out.data.nonzero()
        out.data[nz] /= column_repeated[nz]
        if convert_to_csr:
            out = out.tocsr()
    else:
        out /= column[:, np.newaxis]
    return out


def xlogx(x, out=None, in_place=False):
    """Compute x * log_2(x).

    We define 0 * log_2(0) = 0

    Parameters
    ----------
    x : np.ndarray or scipy.sparse.csc_matrix or csr_matrix
        The input array.
    out : same type as x (optional)
        If provided, use this array/matrix for the result.
    in_place : bool (optional, default False)
        Operate directly on x.

    Returns
    -------
    y : same type as x
        Result of x * log_2(x).
    """
    if in_place:
        y = x
    elif out is None:
        y = x.copy()
    else:
        y = out
    if type(y) in [sparse.csc_matrix, sparse.csr_matrix]:
        z = y.data
    else:
        z = y
    nz = z.nonzero()
    z[nz] *= np.log2(z[nz])
    return y

# Functions for evaluating binary segmentation


def confusion_matrix(pred, gt, thres=0.5):
    """Calculate the confusion matrix given a probablility threshold in (0,1).
    """
    TP = np.sum((gt == 1) & (pred > thres))
    FP = np.sum((gt == 0) & (pred > thres))
    TN = np.sum((gt == 0) & (pred <= thres))
    FN = np.sum((gt == 1) & (pred <= thres))
    return (TP, FP, TN, FN)


def get_binary_jaccard(pred, gt, thres=[0.5]):
    """Evaluate the binary prediction at multiple thresholds using the Jaccard 
    Index, which is also known as Intersection over Union (IoU). If the prediction
    is already binarized, different thresholds will result the same result.

    Args:
        pred (numpy.ndarray): foreground probability of shape :math:`(Z, Y, X)`.
        gt (numpy.ndarray): binary foreground label of shape identical to the prediction.
        thres (list): a list of probablility threshold in (0,1). Default: [0.5]

    Return:
        score (numpy.ndarray): a numpy array of shape :math:`(N, 4)`, where :math:`N` is the 
        number of element(s) in the probability threshold list. The four scores in each line
        are foreground IoU, IoU, precision and recall, respectively.
    """
    score = np.zeros((len(thres), 4))
    for tid, t in enumerate(thres):
        assert 0.0 < t < 1.0, "The range of the threshold should be (0,1)."
        TP, FP, TN, FN = confusion_matrix(pred, gt, t)

        precision = float(TP)/(TP+FP)
        recall = float(TP)/(TP+FN)
        iou_fg = float(TP)/(TP+FP+FN)
        iou_bg = float(TN)/(TN+FP+FN)
        iou = (iou_fg + iou_bg) / 2.0
        score[tid] = np.array([iou_fg, iou, precision, recall])
    return score


def cremi_distance(pred, gt, resolution=(40.0, 4.0, 4.0)):
    """Compute the FP/FN statistics between predictions and ground truth as
       in the CREMI challenge (https://cremi.org/). Both inputs (pred, gt) need 
       to be of the same size.
    """
    def count_false_positives(test_clefts_mask, truth_clefts_edt, threshold=200):
        mask1 = np.invert(test_clefts_mask)
        mask2 = truth_clefts_edt > threshold
        false_positives = truth_clefts_edt[np.logical_and(mask1, mask2)]
        return false_positives.size

    def count_false_negatives(truth_clefts_mask, test_clefts_edt, threshold=200):
        mask1 = np.invert(truth_clefts_mask)
        mask2 = test_clefts_edt > threshold
        false_negatives = test_clefts_edt[np.logical_and(mask1, mask2)]
        return false_negatives.size

    def acc_false_positives(test_clefts_mask, truth_clefts_edt):
        mask = np.invert(test_clefts_mask)
        false_positives = truth_clefts_edt[mask]
        stats = {
            'mean': np.mean(false_positives),
            'std': np.std(false_positives),
            'max': np.amax(false_positives),
            'count': false_positives.size,
            'median': np.median(false_positives)}
        return stats

    def acc_false_negatives(truth_clefts_mask, test_clefts_edt):
        mask = np.invert(truth_clefts_mask)
        false_negatives = test_clefts_edt[mask]
        stats = {
            'mean': np.mean(false_negatives),
            'std': np.std(false_negatives),
            'max': np.amax(false_negatives),
            'count': false_negatives.size,
            'median': np.median(false_negatives)}
        return stats

    def convert_dtype(data):
        data = data.astype(np.uint64)
        data[data == 0] = 0xffffffffffffffff
        return data

    test_clefts = convert_dtype(pred)
    truth_clefts = convert_dtype(gt)

    truth_clefts_invalid = truth_clefts == 0xfffffffffffffffe

    test_clefts_mask = np.logical_or(
        test_clefts == 0xffffffffffffffff, truth_clefts_invalid)
    truth_clefts_mask = np.logical_or(
        truth_clefts == 0xffffffffffffffff, truth_clefts_invalid)

    print("EDT calculation in progress")
    test_clefts_edt = ndimage.distance_transform_edt(test_clefts_mask, sampling=resolution)
    truth_clefts_edt = ndimage.distance_transform_edt(truth_clefts_mask, sampling=resolution)

    false_positive_count = count_false_positives(
        test_clefts_mask, truth_clefts_edt)
    false_negative_count = count_false_negatives(
        truth_clefts_mask, test_clefts_edt)

    false_positive_stats = acc_false_positives(
        test_clefts_mask, truth_clefts_edt)
    false_negative_stats = acc_false_negatives(
        truth_clefts_mask, test_clefts_edt)

    print("Clefts Statistics")
    print("======")

    print("\tfalse positives: " + str(false_positive_count))
    print("\tfalse negatives: " + str(false_negative_count))

    print("\tdistance to ground truth: " + str(false_positive_stats))
    print("\tdistance to proposal    : " + str(false_negative_stats))

    return false_positive_stats['mean'], false_negative_stats['mean']

def min_max(vol):
    '''
    Min max normalization for volume

    Parameters
    --
    - vol: takes in volume for normalization
    
    Returns
    --
    - vol: after normalization
    '''

    return (vol - vol.min())/(vol.max()-vol.min())


def evaluations(prediction_folder, gt_path, metric='confusion', threshold = [0.5, 0.8, 0.9]):
    '''
    Taken a folder path where a list of volumes is within the path, evaluate (based on the metric) 
    of each volume w.r.t. the groundtruth.

    Parameters
    ----
    - prediction_folder: str, path to the prediction folder, that contains a list of volumes
    - gt_path: str, path to the groundtruth volume
    - metric: str, ('confusion', 'jac', 'adapted_rand', 'voi')
    - threshold: opt, list of threshold 

    Returns
    ----
    - {n1:score1,n2:score2,...}: dictionary, of shape scores x N x M, where N is the number of volumes within the folder, M is the 
    different threshold we want to evaluate. 
    '''

    assert metric in ('confusion', 'jac', 'adapted_rand', 'voi')
    vol_dict = {}
    gt = tifffile.imread(gt_path)
    for f in os.listdir(prediction_folder):
        if not f.endswith('tif'): continue
        path = os.path.join(prediction_folder,f)
        v = tifffile.imread(path)
        k = f.replace('.tif','')
        vol_dict[k] = v

    score_D = {}
    for k,v in vol_dict.items():
        if metric == 'confusion':
            if gt.max()>1:
                gt = min_max(gt)
            if v.max()>1:
                v = min_max(v)
            for thres in threshold:
                score_D[str(thres)] = score_D.get(str(thres),{}) 
                score_D[str(thres)][k] = confusion_matrix(v,gt,thres) # (TP, FP, TN, FN)
        elif metric == 'jac':
            if gt.max()>1:
                gt = min_max(gt)
            if v.max()>1:
                v = min_max(v)
            score_arr = get_binary_jaccard(v,gt,thres=threshold)
            for i,thres in enumerate(threshold):
                score_D[str(thres)] = score_D.get(str(thres),{}) 
                score_D[str(thres)][k] = score_arr[i]
        elif metric == 'adapted_rand':
            assert v.dtype == np.uint8 and gt.dtype == np.uint8
            score_D[k] = adapted_rand(v,gt,all_stats=True)
        elif metric == 'voi':
            assert v.dtype == np.uint8 and gt.dtype == np.uint8
            score_D[k] = voi(v,gt)

    return score_D


if __name__ == '__main__':
    folder_path = "/Users/yananw/Downloads/stridetest/"
    gt_path = "/Users/yananw/Downloads/stridetest/4x64x64.tif"
    D1 = evaluations(folder_path,gt_path,metric='confusion')  #(TP, FP, TN, FN) 
    D2 = evaluations(folder_path,gt_path,metric='jac') # (foreground IoU, IoU, precision and recall)
    D3 = evaluations(folder_path,gt_path,metric='adapted_rand') #(err, adapted precision, adapted recall)
    D4 = evaluations(folder_path,gt_path,metric='voi') #(split, merge)

    print(D1,D2)
    
    

    
