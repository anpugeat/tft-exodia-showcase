"""
TFTExodia - main.py: This is the main entry point for our pipeline.

This file orchestrates the entire pipeline, from scraping data to running the analysis and exporting the results.
Run as a script for a standard incremental update + analysis cycle.

NOTE: This is a public showcase version of the project. The structure is reflected, but several modules 
(clustering_cleanup, comp_accessory_stats, unit_stats, proprocessing), and the tuned analysis hyperparameters are kept private.

Live results are published at https://tftexodia.com.
"""

from src.config import analysis_config, scraping_config
from src.database import db_commands
from src.scraping import scrape_matches,update_playerbase,api_utils
from src.modelling import preprocessing,clustering,clustering_cleanup,comp_accessory_stats,unit_stats
from src.version_control import versions
import logging

# See the logs at level "INFO" from our scripts
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# ---------------------------------------------------------------------------------- #
#                                      DATABASE                                      #
# ---------------------------------------------------------------------------------- #
def restart_database(num_of_players=1000):
    """
    Database nuker.

    Wipes our database, rebuilds the table schemas, refershes tracked player list, and performs a
    fresh scrape. 
    """
    # Nuke the old database
    db_commands.nuke_database()

    # Initialise new database
    db_commands.init_db()

    # Update our player list
    update_playerbase.update_playerbase(**scraping_config)

    # Scrape matches from our player list
    scrape_matches.match_scraper(num_of_players)


def update_database(num_of_players=1000):
    """
    Standard daily update.

    Refreshes our tracked player list and scrapes new matches for the `num_of_player` stalest
    players. Already-processed matches are skipped via the `processed_matches` ledger.
    """
    # Update our player list
    update_playerbase.update_playerbase(**scraping_config)

    # Scrape matches from our player list
    scrape_matches.match_scraper(num_of_players)


# ---------------------------------------------------------------------------------- #
#                                  ANALYSIS PIPELINE                                 #
# ---------------------------------------------------------------------------------- #
def run_analysis(to_csv=False):
    """
    Full analysis pipeline.

    Stages:
        1. Preprocessing      — extract and clean participant boards from raw matches
        2. Clustering         — UMAP dimensionality reduction + HDBSCAN clustering
        3. Cluster cleanup    — clean up compositions                       (private)
        4. Accessory stats    — carries, BIS items, misc comp stats         (private)
        5. Unit tier list     — unit rankings                               (private)
        6. Versioning         — tracks daily updates and comp trends over time
 
    Tuned hyperparameters are read from `ANALYSIS_CONFIG`. Production values
    are kept in the private config; the public template ships with neutral
    defaults that are sensible but not optimal.
    """
    # 1. Preprocessing
    preprocessing.create_unit_index()
    units_df,traits_df,placement_df = preprocessing.extract_participant_boards()
    participant_boards = preprocessing.preprocess_participant_boards(units_df,placement_df,analysis_config['duplicate_threshold'])
    
    # 2. Clustering
    clusterable_embedding = clustering.umap_reduce(participant_boards)
    participant_boards['umap_x'] = clusterable_embedding[:, 0]
    participant_boards['umap_y'] = clusterable_embedding[:, 1]
    participant_boards['cluster'] = clustering.apply_hdbscan(clusterable_embedding)
    participant_boards.sort_values(by='cluster', inplace=True)
    comp_metrics_df = clustering.cluster_metrics(participant_boards)

    # 3. Cluster cleanup
    comp_metrics_df = clustering_cleanup.reassign_duplicate_comps(comp_metrics_df)
    parent_comps,superset_comps,comp_mapping = clustering_cleanup.absorb_comps(comp_metrics_df,similarity_subset=analysis_config['similarity_subset'],similarity_superset=analysis_config['similarity_superset'])
    meta_parent_comps,offmeta_parent_comps = clustering_cleanup.filter_meta_comps(parent_comps)
    participant_boards = clustering_cleanup.map_parent_index(participant_boards, comp_mapping, meta_parent_comps)
    
    # 4. Accessory stats
    meta_parent_comps,carry_playrate,reroll_playrate = comp_accessory_stats.identify_carries_rerolls(participant_boards,meta_parent_comps)
    carry_item_metrics = comp_accessory_stats.identify_bis_items(participant_boards, meta_parent_comps)
    meta_parent_comps = comp_accessory_stats.assign_carry_items(meta_parent_comps, carry_item_metrics)
    meta_parent_comps = comp_accessory_stats.map_traits(meta_parent_comps)
    meta_parent_comps['comp_name'] = meta_parent_comps.apply(comp_accessory_stats.comp_namer,axis=1)
    meta_parent_comps = comp_accessory_stats.get_firstRate(participant_boards,meta_parent_comps)
    meta_parent_comps = comp_accessory_stats.get_pickRate(participant_boards,meta_parent_comps)
    meta_parent_comps = comp_accessory_stats.get_trending(meta_parent_comps)
    meta_parent_comps = comp_accessory_stats.get_comp_tier(meta_parent_comps)
    meta_parent_comps = comp_accessory_stats.get_compType(meta_parent_comps,units_df)

    # 5. Unit Tierlist
    unit_tierlist = unit_stats.generate_unit_tier_list(units_df,participant_boards,carry_item_metrics,min_star_level=analysis_config['min_star_level'])

    # 6. Versioning
    meta_parent_comps = versions.version_manager(meta_parent_comps, filepath='data', lookback_days=analysis_config['lookback_days'], trending_quantile=['trending_quantile'])

    if to_csv:
        participant_boards.to_csv("participant_boards.csv")
        units_df.to_csv("units_df.csv")
        traits_df.to_csv("traits_df.csv")
        parent_comps.to_csv("parent_comps.csv")
        superset_comps.to_csv("superset_comps.csv")
        offmeta_parent_comps.to_csv('offmeta_parent_comps.csv')
        carry_playrate.to_csv('carry_playrate.csv')
        reroll_playrate.to_csv('reroll_playrate.csv')
        carry_item_metrics.to_csv('carry_item_metrics.csv')
        meta_parent_comps.to_csv('meta_parent_comps.csv')
        unit_tierlist.to_csv('unit_tierlist.csv')
    


# -------------------------------------------------------------------------------- #
#                            DAILY UPDATE ENTRY POINT                              #
# -------------------------------------------------------------------------------- #

if __name__ == "__main__":
    logging.info("=== Database Update: Run started ===")
    update_database(num_of_players=100)
    run_analysis(to_csv=True)
    logging.info("=== Database Update: Run finished ===")


# -------------------------------------------------------------------------------- #
#                            ALTERNATIVE: FULL REFRESH                             #
# -------------------------------------------------------------------------------- #

'''
# FULL REFRESH: NUKE & UPDATE DATABASE
if __name__ == "__main__":
    logging.info("=== Database Refresh: Run started ===")
    restart_database(num_of_players=200)
    run_analysis(to_csv=True)
    logging.info("=== Database Refresh: Run finished ===")
'''