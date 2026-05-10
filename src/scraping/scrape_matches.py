'''
Our match scraper. 
1. Go through each player's match history (20 most recent matches) in order of "stalest" player (using last_checked_for_matches)
2. Extract match information from each match and store in the matches, participants, participant_units and participant_traits tables.
3. Before scraping a match, first check that it doesn't already exist in processed_matches. After scraping a match, enter the match id into processed matches.
4. Update the last_checked_for_matches after scraping too!
'''

# Imports
import logging

from src.scraping.api_utils import continent_map, api_request
from src.config import api_key, set_number,current_patch_release_date, matches_per_player   # load our database connection string, Riot API key and scraping variables from config
from src.database import db_commands   # loads commands required to interact with our database


# ----------------------------------- RIOT API ----------------------------------- #
# Some of Riot's API URLs require a region, and not the specific region. We map this to simplify.
continent_map = {
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe",
    "kr": "asia", "jp1": "asia",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea"
}


# ----------------------------- MATCH INFO EXTRACTOR ----------------------------- #
# Unpacks all the data we need from each match as lists of tuples so that we can insert them into our tables.
def match_info_unpacker(match_id, match_data):
    # -- INTIALISE --
    match_data_to_insert = []
    participants_data_to_insert = []
    units_data_to_insert = []
    traits_data_to_insert = []

    # Let's first extract all of the info we can from this match into Python as tuples
    # -- MATCH INFO --
    match_tuple = (
        match_id,
        match_data['info']['game_version'],
        match_data['info']['game_datetime'],
        match_data['info']['queueId'],
        match_data['info']['tft_set_number']  
    )
    match_data_to_insert.append(match_tuple)

    # -- PARTICIPANT INFO --
    # participant_id: A unique ID for each participant of each game, created using "match_id" + "_" + "1-8" (1-8 indexing player 1 through 8 of the match)
    for part_index, part_data in enumerate(match_data['info']['participants']):
        participant_id = f"{match_id}_{part_index+1}"

        # All of the data we need to extract about the participant becomes a tuple to append. This makes it easier to insert into SQL later.
        participant_tuple = (
            participant_id,
            match_id,
            part_index+1,  # participant index (#1-8 of the game)
            part_data['puuid'],
            part_data['riotIdGameName'],
            part_data['placement'],
            part_data['win'],
            part_data['level'],
            part_data['gold_left'],
            part_data['last_round'],
            part_data['time_eliminated'],
            part_data['total_damage_to_players'],
            part_data['players_eliminated']
        )
        participants_data_to_insert.append(participant_tuple)

        # -- UNITS INFO --
        # Loop through the units for each participant while we're still inside the loop for each player
        for unit_index, unit in enumerate(part_data['units']):
            # unit_case_id: Unique ID for every time a unit was used. Defined by "match_id"+"_"+"participant_index"+"_"+"unit index"
            unit_case_id = f"{match_id}_{part_index}_{unit_index+1}"

            units_tuple = (
                unit_case_id,
               participant_id,
                unit['character_id'],
                unit['tier'],
                unit['rarity'],
                # Conditional: If unit has items, then add into tuple.
                unit['itemNames'][0] if len(unit['itemNames']) > 0 else None,  # item 1 
                unit['itemNames'][1] if len(unit['itemNames']) > 1 else None,  # item 2 
                unit['itemNames'][2] if len(unit['itemNames']) > 2 else None,  # item 3
            )
            units_data_to_insert.append(units_tuple)

        # -- TRAITS INFO --
        # Same as for units, loop through each trait to record info
        for trait_index, trait in enumerate(part_data['traits']):
            # Same thing here, we have a unique trait case ID comprising match_id, participant index and the trait's index
            trait_case_id = f"{match_id}_{part_index}_{trait_index+1}"

            traits_tuple = (
                trait_case_id,
                participant_id,
                trait['name'],
                trait['num_units'],
                trait['tier_current'],
                trait['tier_total'],
                trait['style']
            )
            traits_data_to_insert.append(traits_tuple)

    return match_data_to_insert,participants_data_to_insert,units_data_to_insert,traits_data_to_insert


# -------------------------- MATCH INFO INSERTER TO DB --------------------------- #
# Inserts our extracted lists from 'match_info_extracted' into our database
def match_info_inserter(match_data_to_insert,participants_data_to_insert,units_data_to_insert,traits_data_to_insert,match_id):
    conn = db_commands.db_connect()
    cursor = conn.cursor()

    try:
        # 1. Insert Match Data
        match_query = """
            INSERT INTO matches (match_id,game_version,game_datetime,queue_id,tft_set_number)
            VALUES (%s, %s, to_timestamp(%s / 1000.0), %s, %s)   -- Convert to TIMESTAMP from BIGINT
            ON CONFLICT (match_id) DO NOTHING;
        """
        cursor.executemany(match_query, match_data_to_insert)

        # 2. Insert Participants Data
        participants_query = """
            INSERT INTO participants (participant_id,match_id,participant_index,puuid,summoner_name,
                                      placement,win,level,gold_left,last_round,time_eliminated,
                                      total_damage_to_players,players_eliminated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (participant_id) DO NOTHING;
        """
        cursor.executemany(participants_query, participants_data_to_insert)

        # 3. Insert Units Data
        units_query = """
            INSERT INTO participant_units (unit_case_id,participant_id,character_id,tier,rarity,
                                           item_1_id,item_2_id,item_3_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (unit_case_id) DO NOTHING;
        """
        cursor.executemany(units_query, units_data_to_insert)

        # 4. Insert Traits Data
        traits_query = """
            INSERT INTO participant_traits (trait_case_id,participant_id,trait_name,num_units,
                                            tier_current,tier_total,style)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trait_case_id) DO NOTHING;
        """
        cursor.executemany(traits_query,traits_data_to_insert)

        conn.commit()

    except Exception as e:
        conn.rollback()  # add this so that if any query fails, we undo all our changes in this instanc to avoid partial data inserts
        logging.error(f"Error inserting match data for match {match_id}. Error: {e}")
    finally:
        cursor.close()
        conn.close()

# -------------------------------- MATCH SCRAPER --------------------------------- #
# Scrape our matches! Repeats num_of_players times
def match_scraper(num_of_players):
    for _ in range(num_of_players):
        conn = db_commands.db_connect()    # connect with our database!
        cur = conn.cursor()

        try:
            # Identify the stalest player in top_players using our B-Tree index
            cur.execute("""
                SELECT puuid, region FROM top_players
                ORDER BY last_checked_for_matches ASC NULLS FIRST
                LIMIT 1;
            """)
            player_info = cur.fetchone()   # take only one result (one player)

            if player_info is None:  # handle error case where top_players is empty
                logging.info("Match scraper error: No players found in top_players table!")
                return
        
            player_puuid, player_region = player_info
            player_continent = continent_map.get(player_region.lower(),"asia")
            logging.info(f"Processing match history for player {player_puuid} [{player_region}]")

            # Update their "staleness" factor
            cur.execute("""
                UPDATE top_players
                SET last_checked_for_matches = NOW()
                WHERE puuid = %s;
            """, (player_puuid,))
            conn.commit()

            # Fetch their last 20 matches. Match history URLs are less prone to change so we don't need a match_URL_builder here.
            match_history_url = f"https://{player_continent}.api.riotgames.com/tft/match/v1/matches/by-puuid/{player_puuid}/ids?start=0&startTime={current_patch_release_date}&count={matches_per_player}&api_key={api_key}"
            player_match_ids = tuple(api_request(match_history_url))  # turn match ids into tuples as this is how SQL takes in data

            # Filter matches we've already processed!
            cur.execute("""
                SELECT match_id 
                FROM processed_matches 
                WHERE match_id IN %s;
            """, (player_match_ids,))
        
            # Identify and record duplicate matches (ones we've already scraped)
            duplicate_matches = []
            for row in cur.fetchall():
                duplicate_matches.append(row[0])  # Move duplicate matches into a list

            # Subtract our duplicate matches from the player's matches to identify which ones we want to scrape
            player_matches_to_scrape = []
            for m_id in player_match_ids:
                if m_id not in duplicate_matches:
                    player_matches_to_scrape.append(m_id)
            logging.info(f'Found {len(player_matches_to_scrape)} new matches to process!')
        
            # Start processing our matches from player_matches_to_scrape!
            for match_id in player_matches_to_scrape:
                match_details_url = f"https://{player_continent}.api.riotgames.com/tft/match/v1/matches/{match_id}?api_key={api_key}"
                match_data = api_request(match_details_url)  # extract match data using Riot API URL

                # Check if the match is specifically from TFT Set 16
                if match_data['info']['tft_set_number'] == set_number:
                    # Now we unpack the .json file received from Riot's API into tuples using our predefined function
                    match_data_to_insert,participants_data_to_insert,units_data_to_insert,traits_data_to_insert = match_info_unpacker(match_id,match_data)

                    # Each of the above is a list of tuples for each match, participant, unit, etc. We insert this into our database:
                    match_info_inserter(match_data_to_insert,participants_data_to_insert,units_data_to_insert,traits_data_to_insert,match_id)

                # Enter the match id into processed_matches after successful scraping
                cur.execute("""
                    INSERT INTO processed_matches (match_id)
                    VALUES (%s)
                    ON CONFLICT (match_id) DO NOTHING;
                """, (match_id,))
                conn.commit()

                logging.info(f"Successfully processed and logged match {match_id}!")

        except Exception as e:
            logging.error(f"Error encountered in match scraper: {e}")
            conn.rollback()   # add this so that if any query fails, we undo all our changes in this instanc to avoid partial data inserts
        finally:
            cur.close()
            conn.close()




