'''
This file updates our apex player list in our database to ensure our player "phone book" is up to date.
Once we have a list of current Master+ tier players, we can then scrape their match history.
'''

import requests   # for interacting with Riot API
from psycopg2 import extras   # useful for inserting entire rows at a time into SQL to simplify insertion
import logging    # for recording errors
from src.config import api_key,delete_matches_after   # load our Riot API key
from src.database import db_commands   # loads commands required to interact with our database
from src.scraping.api_utils import league_url_builder  # loads our league URL builder function

# -------------------------------- UPDATE PLAYERBASE ------------------------------- #

def update_playerbase(regions, tiers, queue):

    db_commands.delete_old_matches(days=delete_matches_after)

    conn = db_commands.db_connect()   # connect with our database!
    cur = conn.cursor()   # cursor object which we execute sql commands with

    # Iterate through each region and tier to extract everyone
    for region in regions:
        for tier in tiers:
            try:
                # Extract current Chall/GM/Master list of players in the given region/tier
                print(f"Retrieving playerlist for {region} {tier}...")
                api_url = league_url_builder(region,tier,queue,api_key)   # build our API URL
                resp = requests.get(api_url)   # make the request to Riot
                player_data = resp.json()  # save the response

                upsert_list = []   # placeholder for all of our player info

                for player in range(len(player_data['entries'])):
                    puuid = player_data['entries'][player]['puuid']
                    league_points = player_data['entries'][player]['leaguePoints']

                    # Tuple of player's details so we can insert into database as a row.
                    current_player_info = (
                        puuid,
                        region,
                        tier,
                        league_points,
                        # last_updated will be handled by SQL to assign the current time when added
                    )

                    # Append our placeholder with the current player's information as a tuple
                    upsert_list.append(current_player_info)

                # Define our "Upsert" query, which inserts player information. If puuid already exists, update their info.
                query = """
                    INSERT INTO top_players (puuid,region,tier,league_points)
                    VALUES %s
                    ON CONFLICT (puuid)
                    DO UPDATE SET
                        region = EXCLUDED.region,
                        tier = EXCLUDED.tier,
                        league_points = EXCLUDED.league_points,
                        last_updated = NOW();  -- Update last_updated to current time!
                """

                # Here, execute_values() uses our query, and uses the tuples from upsert_list to fill out the rows we are inserting into top_players.
                extras.execute_values(cur, query, upsert_list)
                conn.commit()
                print(f"Upserted info on {len(upsert_list)} players!")

            except requests.exceptions.RequestException as e:
                    logging.error(f"API Request Error for {region} {tier}: {e}")
            except Exception as e:
                    logging.error(f"Database error for {region} {tier}: {e}")
