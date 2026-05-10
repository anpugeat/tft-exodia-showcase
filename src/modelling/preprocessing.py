"""
preprocessing.py: Pulls scraped match data out of PostgreSQL and reshapes it into participant-level
structure to feed into the clustering and stats pipelines.

Outputs 'participant_boards' Dataframe, with one row per player per match and the schema:
    participant_id : str   — primary key
    placement      : int   — 1-8 final placement
    is_top_4       : bool  — convenience flag for top-half finishes
    composition    : list  — units on the final board
    carries        : list  — units holding 2+ items
    rerolls        : list  — units played at 3-star (reroll signal)
    carry_items    : dict  — carry unit -> list of items
    comp_length    : int   — total number of units on the board

Tunable parameters are read from `analysis_config` in src.config.
"""

import logging
import pandas as pd
from src.database import db_commands
from collections import Counter
from src.config import remove_units, analysis_config


# ---------------------------------------------------------------------------- #
#                            UNIT INDEX TABLE CREATION                         #
# ---------------------------------------------------------------------------- #
def create_unit_index():
    '''
    Creates a new SQL table called unit_index, which records each unique unit (Kennen, Kogmaw) in one column, and their cost (rarity) in the next. Based off of Riot's data, the translation is as follows:
    - rarity 0: 1 cost
    - rarity 1: 2 cost
    - rarity 2: 3 cost
    - rarity 4: 4 cost
    - rarity 6: 5 & 7 costs
    - rarity 9: Unique summon of a 5 cost, i.e. Tibbers
    '''
    conn = db_commands.db_connect()
    cur = conn.cursor()
    logging.info(f"1/2 PREPROCESSING: Creating unit index table...")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS unit_index AS
            SELECT DISTINCT 
            REPLACE(character_id, 'TFT16_', '') AS unit_name, 
            rarity
        FROM participant_units;
    """)

    conn.commit()
    logging.info("2/2 PREPROCESSING: Unit index table created successfully!")
    return 


# ---------------------------------------------------------------------------- #
#                  PARTICIPANT BOARD EXTRACTION (SQL -> PANDAS)                #
# ---------------------------------------------------------------------------- 
def extract_participant_boards():
    '''
    Extracts participant board data from our PostgreSQL database into three dataframes.

    Returns:
    - units_df: per-participant rows with tier, items, derived cost
    - traits_df: active traits per participant
    - placement_df: final placement and top-4 flag per participant
    '''
    conn = db_commands.db_connect()
    logging.info(f'1/2 PREPROCESSING: Extracting participant boards from SQL database into Pandas')

    # 1. Extract units from each participant
    units_query = """
        SELECT
            participant_id,
            character_id,
            tier,
            rarity,
            item_1_id,
            item_2_id,
            item_3_id
        FROM participant_units;
    """
    units_df = pd.read_sql_query(units_query, conn)

    # 2. Extract active traits from each participant
    # Note: only pull traits where the current tier is greater than 1 (i.e. remove ones where we have a stray bruiser on the team)
    traits_query = """
        SELECT
            participant_id,
            trait_name,
            tier_current
        FROM participant_traits
        WHERE tier_current > 0;
    """
    traits_df = pd.read_sql_query(traits_query, conn)

    # 3. Extract placement/win data from each participant's game
    placement_query = """
        SELECT 
            participant_id, 
            placement, 
            win AS is_top_4
        FROM participants;
    """
    placement_df = pd.read_sql_query(placement_query, conn)
    conn.close()

    # Remove "TFT16_" and "tft16_" (lower-case for atakhan only... i don't know why @Riot...) from all of our unit names and trait names
    clean_regex = r'(?i)TFT.*?_'
    units_df = units_df.replace(clean_regex, '', regex=True)
    traits_df = traits_df.replace(clean_regex, '', regex=True)

    # 4. Derive unit cost from rarity
    # Rarity mapping: 0->1c, 1->2c, 2->3c, 4->4c, 6+->5c (rarities 3 and 5 are
    # unused in standard sets but may appear for special/traited units)
    cost_map = {0: 1, 1: 2, 2: 3, 4: 4}
    units_df['cost'] = units_df['rarity'].map(cost_map)
    units_df.loc[units_df['rarity'] >= 6, 'cost'] = 5
    units_df['cost'] = units_df['cost'].astype('Int64')  # nullable int preserves NaN for unmapped rarities

    unmapped = units_df['cost'].isna().sum()
    if unmapped:
        bad_rarities = sorted(units_df.loc[units_df['cost'].isna(), 'rarity'].unique())
        logging.warning(
            f"1/2 PREPROCESSING: {unmapped} unit rows have unmapped rarity values: {bad_rarities}"
        )

    logging.info(f"1/2 PREPROCESSING: Participant board extraction complete!")

    # 5. Configure duplicate units
    units_df = configure_units(units_df, remove_units)

    return units_df, traits_df, placement_df


# ---------------------------------------------------------------------------- #
#                    REMOVE EXCLUDED UNITS & SORT DUPLICATES                   #
# ---------------------------------------------------------------------------- #
def configure_units(units_df,remove_units):
    '''
    Drop excluded units and sort so the strongest copy of duplicates is first.
    
    Some units (summons, ability-spawned helpers) appear on the board but
    aren't part of the player's chosen composition - these are listed in
    `remove_units` and stripped here.

    For legitimate duplicates (e.g. the Double Trouble augment giving two
    Malzahars), we sort by tier and item count descending so downstream code
    can treat the first occurrence as the primary copy.
    '''
    logging.info("PREPROCESSING: Configuring duplicate units and removing excluded units...")
    initial_units_len = len(units_df)

    # 1. REMOVE UNITS FROM "remove_units"
    if remove_units:
        # Lowercase remove_units to account for upper and lower case:
        remove_units_lowercase = [unit.lower() for unit in remove_units]

        # Keep only rows where lowercased character_id does NOT match remove_list
        units_df = units_df[~units_df['character_id'].str.lower().isin(remove_units_lowercase)]

    units_removed = initial_units_len - len(units_df)
    logging.info(f"PREPROCESSING: Removed {units_removed} units from remove_units list!")

    # 2. COUNT ITEMS
    item_slots = ['item_1_id', 'item_2_id', 'item_3_id']
    units_df['item_count'] = units_df[item_slots].count(axis=1)
    
    # 3. SORT DATAFRAME
    # We group by participant and character, then sort by tier (descending) and items (descending).
    # This guarantees the "strongest" version of a duplicate unit is listed first.
    units_df = units_df.sort_values(
        by=['participant_id', 'character_id', 'tier', 'item_count'],
        ascending=[True, True, False, False]
    )
    
    # 4. Re-sort by index to maintain original order
    units_df = units_df.sort_index()
    
    return units_df


# ---------------------------------------------------------------------------- #
#                            FILTER ANOMALOUS BOARDS                           #
# ---------------------------------------------------------------------------- #
# Looking at participant_boards, I noticed a lot of top4 finishes have players who have sold their team to YOLO for a 3* four or five cost unit.
# Their endgame board will be three 2* Ambessas or something similar. Here we create a filtering layer which catches all of these cases.
def filter_random_boards(participant_boards,duplicate_threshold):
    """
    Drops boards that aren't representative of normal play:

    1. YOLO 3-stars: A player sells most of their board chasing a 3-star 4/5 cost unit. Their board
                     may consist of > 2 copies of the same unit and some random filler units.
    2. Unicorn boards: Boards with very few units (sold team) or unusually many units (edge cases)
                       which don't reflect typical comps.
    """
    # Record how many boards we started with so we can track how many we remove due to anomalous boards
    initial_board_count = len(participant_boards)

    # Use a list comprehension to strip "_copy" before counting, so all base units and copies are counted together
    participant_boards['duplicate_units'] = participant_boards['composition'].apply(
        lambda x: {unit: count for unit, count in Counter([u.replace('_copy', '') for u in x]).items() if count >= duplicate_threshold}
    )

    # If the duplicate_units column is populated, remove the row entirely. It means most likely the player has sold their board
    participant_boards = participant_boards[participant_boards['duplicate_units'].apply(len) == 0]

    # Also remove boards where they have <= 4 units, as it's pretty much impossible to die before level 5. Thus, they must have sold their board for some reason. Also remove unicorn boards of >= 11 units
    participant_boards = participant_boards[(participant_boards['comp_length'] > analysis_config['min_comp_length']) & (participant_boards['comp_length'] < analysis_config['max_comp_length'])]

    # Calculate how many rows were removed, and log it
    boards_removed = initial_board_count - len(participant_boards)
    logging.info(f"Removed {boards_removed} troll boards consisting of {duplicate_threshold} or more of the same unit, or less than 4 total units!")

    # Remove duplicate_units column. It was temporary and also it is now empty!
    participant_boards = participant_boards.drop(columns=['duplicate_units'])

    return participant_boards


# ---------------------------------------------------------------------------- #
#                       COMPOSITE PREPROCESSING FUNCTION                       #
# ---------------------------------------------------------------------------- #
# This function brings it all together.

# Note: The following are true for our composition recommender:
# - We do not recommend 1* units as everybody knows it's ideal to strive for a 2* or 3* -> All 1* and 2* units become just units, i.e. Kennen_2, Kennen_1 become Kennen.
# - 3* units temporarily become just the raw unit aswell (Kennen) but are stored in a separate "rerolls" column. We will later use them as part of an upgrade_rate() algorithm to determine if the composition requires to reroll for the unit.
# - All 3* units with rarity >= 4 become just their regular unit (Yunara) AND ARE NOT STORED IN THE "rerolls" COLUMN. This is because 3* high-cost units are in unicorn comps and are not achievable in most games.

def preprocess_participant_boards(units_df,placement_df,duplicate_threshold=3):
    '''
    Reshapes our per-unit rows from units_df into per-participant-per-game `participant_boards` 
    dataframe, with the following format:

    participant_id | placement | is_top_4 | composition (List, example: [Ahri, Blitzcrank]) | carries (List: Ahri, Azir) | rerolls (List: Ahri, Milio)
    '''
    logging.info(f"2/2 PREPROCESSING: Restructuring participant boards...")

    # --------------- Composition column creation ------------------ #
    # Create a "composition" dataframe which is a list of all units on the board
    compositions_df = units_df.groupby('participant_id')['character_id'].apply(list).reset_index()
    compositions_df.rename(columns={'character_id':'composition'},inplace=True)

    # --------------- Identify carries ------------------ #
    # Does the unit have >= 2 items? Then is_carry column == True
    # Note: 'item_count' is already calculated earlier in configure_units()
    units_df['is_carry'] = units_df['item_count'] >= 2

    # Create a "carries" dataframe consisting of a list of all is_carry == True units
    carries_only = units_df[units_df['is_carry'] == True]
    carries_df = carries_only.groupby('participant_id')['character_id'].apply(list).reset_index()
    carries_df.rename(columns={'character_id': 'carries'}, inplace=True)

    # --------------- Identify reroll units ------------------ #
    # Is the unit 3 or 4 star? Then we add them to the rerolls column
    rerolls_only = units_df[units_df['tier'] >= 3]
    rerolls_df = rerolls_only.groupby('participant_id')['character_id'].apply(list).reset_index()
    rerolls_df.rename(columns={'character_id': 'rerolls'}, inplace=True)

    # --------------- Merge everything for participant_boards ------------------ #
    # Create participant_boards by merging everything with everything!
    participant_boards = pd.merge(compositions_df, carries_df, on='participant_id', how='left')        # Merge compositions and carries
    participant_boards = pd.merge(participant_boards, rerolls_df, on='participant_id', how='left')     # Merge with rerolls
    participant_boards = pd.merge(participant_boards, placement_df, on='participant_id', how='inner')  # Merge with placement dataframe

    participant_boards['comp_length'] = participant_boards['composition'].apply(len)

    # Carry items
    carries_only = carries_only.copy()
    item_cols = ['item_1_id', 'item_2_id', 'item_3_id']
    carries_only['item_list'] = carries_only[item_cols].apply(lambda row: row.dropna().tolist(), axis=1)

    carry_items_df = carries_only.groupby('participant_id').apply(
        lambda x: pd.Series({'carry_items': dict(zip(x['character_id'], x['item_list']))})
    ).reset_index()

    participant_boards = pd.merge(participant_boards, carry_items_df, on='participant_id', how='left')
    participant_boards['carry_items'] = participant_boards['carry_items'].apply(lambda x: x if isinstance(x, dict) else {})

    # Filter out anomalous boards
    participant_boards = filter_random_boards(participant_boards,duplicate_threshold=duplicate_threshold)

    logging.info(f"2/2 PREPROCESSING: Participant boards successfully restructured!")

    return participant_boards

