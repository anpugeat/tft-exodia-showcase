"""
clustering.py: Discovers team compositions (comps) by clustering end-of-match player boards.

Pipeline:
1. Multi-hot encode each board over the champion names.
2. Reduce to 2D with UMAP using the Jaccard metric. Jaccard over Euclidean here to measure overlap similarity.
3. Cluster embedding into HDBSCAN, which handles variable-density clusters and labels outliers as noise.
4. Aggregate per-cluster metrics (mean placement, top-4 rate, play count).
"""

import umap
from sklearn.preprocessing import MultiLabelBinarizer
import hdbscan
import matplotlib.pyplot as plt



# ---------------------------------------------------------------------------- #
#                          UMAP DIMENSIONAL REDUCTION                          #
# ---------------------------------------------------------------------------- #
# Initialize and fit UMAP
def umap_reduce(participant_boards):
    """
    Project participant boards into a 2D embedding suitable for clustering using UMAP reduction.
    """
    # Multi-Hot Encode the Champions
    mlb = MultiLabelBinarizer()
    encoded_boards = mlb.fit_transform(participant_boards['composition'])

    clusterable_embedding = umap.UMAP(
        n_neighbors=50,
        min_dist=0.2,
        n_components=2,
        metric='jaccard',
        random_state=42
    ).fit_transform(encoded_boards)

    plt.figure()
    plt.scatter(
        clusterable_embedding[:, 0],
        clusterable_embedding[:, 1])
    plt.gca().set_aspect('equal', 'datalim')
    plt.title(f'UMAP REDUCED MAPPING', fontsize=24)

    return clusterable_embedding


# ---------------------------------------------------------------------------- #
#                              HDBSCAN CLUSTERING                              #
# ---------------------------------------------------------------------------- #
def apply_hdbscan(clusterable_embedding):
    """
    Cluster 2D embeddings with HDBSCAN. 
    """
    labels = hdbscan.HDBSCAN(
        min_samples=10,
        min_cluster_size=(len(clusterable_embedding)//40)
    ).fit_predict(clusterable_embedding)

    # Your existing scatter plot code
    clustered = (labels >= 0)
    plt.scatter(clusterable_embedding[~clustered, 0],
            clusterable_embedding[~clustered, 1],
            color=(0.5, 0.5, 0.5),
            s=5,
            alpha=0.5)

    plt.scatter(clusterable_embedding[clustered, 0],
            clusterable_embedding[clustered, 1],
            c=labels[clustered],
            s=5,
            cmap='Spectral')

    return labels



# ---------------------------------------------------------------------------- #
#                                CLUSTER METRICS                               #
# ---------------------------------------------------------------------------- #
def cluster_metrics(participant_boards):
    comp_metrics_df = participant_boards[['cluster','placement','is_top_4', 'umap_x', 'umap_y']].copy()
    comp_metrics_df['composition'] = participant_boards['composition'].apply(lambda x: tuple(sorted(x)))

    group_by_comp = comp_metrics_df.groupby(['cluster','composition'])

    comp_metrics_df = group_by_comp.agg({
    'placement': 'mean',
    'is_top_4': 'mean',
    'umap_x': 'mean',  
    'umap_y': 'mean'   
    })
    comp_metrics_df['play_count'] = group_by_comp.size()
    comp_metrics_df = comp_metrics_df.reset_index()
    comp_metrics_df['comp_length'] = comp_metrics_df['composition'].apply(len)

    return comp_metrics_df