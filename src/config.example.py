'''
config.py: Central configuration for the project.

Loads connection credentials for the SQL database and the Riot API key from a
local `.env` file so they don't have to be re-loaded in each script. Also
defines the scraping and analysis configuration dicts used across the
pipeline.

NOTE: This is a public showcase version of the project. The analysis hyperparameters
in `analysis_config` are neutiral defaults, and are not the tuned values.

Secrets (database creds, Riot API key) are loaded from a `.env` file which is not
committed. See `.env.example` for the expected structure.
'''

# Import modules
import os
from dotenv import load_dotenv

# Load the .env file
load_dotenv()

# -------------------------------- SCRAPING VARIABLES  ------------------------------- #

sleeptime = 10                             # seconds to sleep after hitting rate limit
current_patch_release_date = 1776211200    # the epoch timestamp release date of our current patch. set to 17th Mar for example
matches_per_player = 20                    # how many matches to scrape when we go through each apex player's match history
set_number = 17                            # current TFT set number

# Region / rank / queue targets for scraping the apex playerbase
scraping_config = {
    "regions": ["kr"],
    "tiers": ["challenger", "grandmaster", "master"],
    "queue": "RANKED_TFT",
}

# ---------------------------------- UNIT CLEANING  ---------------------------------- #

# List of units to remove from our participant boards before calculations. 
# Example format: ["atakhan", "darius"] - not case sensitive
remove_units = ["Atakhan"]


# ------------------------------- BANNED ITEMS FOR BIS  ------------------------------ #
# Items we don't want to keep for BIS calculations like Thiefs Gloves which are random
banned_items = ['Item_ThiefsGloves', 'Item_ThiefsGlovesRadiant']


# -------------------------------- ANALYSIS CONFIG  ---------------------------------- #
# Parameters for our modelling pipeline. These are just examples.
analysis_config = {
    "duplicate_threshold": 5,      # min board duplicates before counting toward a comp
    "similarity_subset": 0.5,     # placeholder — production value is tuned
    "similarity_superset": 0.5,   # placeholder — production value is tuned
    "min_star_level": 2,           # ignore 1-star units in the unit tier list
    "lookback_days": 5,            # window for trending-comp detection
    "trending_quantile": 0.85,      # quantile threshold for "trending" classification
    # Preprocessing
    "min_comp_length": 2,        # boards with <= this many units are dropped
    "max_comp_length": 12,       # boards with >= this many units are dropped
    # Clustering
    "umap_n_neighbors": 30,          # note: these are example values
    "umap_min_dist": 0.1,                 
    "hdbscan_min_samples": 10,
    "hdbscan_cluster_size_divisor": 50,    # min_cluster_size = len(embedding) // this
}

# ------------------------------ DATABASE CONFIGURATION  ----------------------------- #

# Define the config dictionary
db_config = {
    "dbname": os.getenv("db_name"),
    "user": os.getenv("db_user"),
    "password": os.getenv("db_pass"),
    "host": os.getenv("db_host", "localhost"), # Default to localhost if not set in .env
    "port": os.getenv("db_port", "5432")       # Default to port 5432 if not set in .env
}

# Delete matches after X days
delete_matches_after = 10

# ------------------------------------- API KEY  ------------------------------------- #

# Load API Key
api_key = os.getenv("api_key")