'''
db_commands.py:
Here we store functions to interact with our database, including connecting, initialising, 
cleaning up old matches, and nuking the database. We use psycopg2 here to interact with PostgreSQL.
'''

import psycopg2
from psycopg2 import sql
import logging
import sys
from src.config import db_config   # import our database connection string from config.py

# --------------------------------- SQL CONNECTION --------------------------------- #
def db_connect():
    '''Establish a connection to the PostgreSQL datbase using credentials from config.py.'''
    try:
        conn = psycopg2.connect(**db_config)   # use our database config to connect with our PostgreSQL database. '**' unpacks the dictionary.
        return conn
    # If we cannot connect for whatever reason, report the failure and exit so that we don't continue running code without a database connection.
    except Exception as e:
        logging.error(f"Failed to connect to Database: {e}")
        sys.exit(1)

# --------------------------------- DATABASE NUKER --------------------------------- #
# Deletes all tables in our database. For development purposes.
def nuke_database():
    """Drops the public schema and recreates it, removing ALL tables, data, etc."""
    conn = None
    try: 
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("DROP SCHEMA public CASCADE;")
        cur.execute("CREATE SCHEMA public;")
        cur.execute("GRANT ALL ON SCHEMA public TO public;")
        conn.commit()
        print("Database successfully nuked! Hope that wasn't an accident.")
    except Exception as e:
        print(f'Database nuking failed: {e}')
    finally:
        cur.close()
        conn.close()

# -------------------------------- CREATE DATABASE -------------------------------- #
# Creates the tables for our relational database following the tft_database_plan file
def init_db():
    commands = (
        # --- PART 1: Scraping Schema ---
        # a. top_players
        # A list of current Master+ tier players. 
        # We store this list in our database so we don't have to query this over and over and deal with rate limits from Riot.
        # We use the active apex tier players from this list to find matches by scraping their match histories.
        """
        CREATE TABLE IF NOT EXISTS top_players (
            puuid VARCHAR(78) PRIMARY KEY,
            region VARCHAR(5) NOT NULL,
            tier VARCHAR(12),
            league_points SMALLINT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked_for_matches TIMESTAMP
        )
        """,

        # b. idx_job_queue_staleness
        # An index on the "last_checked_for_matches" column in top_players.
        # This is to save time for the scraper. Without the index, our scraper will search through every single row every time it's looking for the next player to scrape, which is costly for memory.
        # With a B-Tree, the index maintains a sorted "tree-like" structure, which allows the scraper to instantly identify the "stalest" player profile to prioritise first. 
        """
        CREATE INDEX IF NOT EXISTS idx_last_checked 
        ON top_players 
        USING btree (last_checked_for_matches ASC NULLS FIRST);
        """,

        # c. processed_matches
        # Prevents matches from being extracted twice. We keep a separate table just for matches already checked, and when they were checked. 
        # The scraper checks against this list before scraping a particular match.
        """
        CREATE TABLE IF NOT EXISTS processed_matches (
            match_id VARCHAR(64) PRIMARY KEY,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # --- PART 2: Database Schema ---
        """
        -- 1. matches table
        CREATE TABLE IF NOT EXISTS matches (
            match_id VARCHAR(64) PRIMARY KEY,
            game_version VARCHAR(255),
            game_datetime TIMESTAMP,
            queue_id INT,
            tft_set_number INT
        )
        """,
        """
        -- 2. participants table
        CREATE TABLE IF NOT EXISTS participants (
            participant_id VARCHAR(64) PRIMARY KEY,
            match_id VARCHAR(64) REFERENCES matches(match_id) ON DELETE CASCADE,
            participant_index SMALLINT,
            puuid VARCHAR(78),
            summoner_name VARCHAR(25),
            placement SMALLINT,
            win BOOLEAN,
            level SMALLINT,
            gold_left SMALLINT,
            last_round SMALLINT,
            time_eliminated FLOAT,
            total_damage_to_players INT,
            players_eliminated SMALLINT
        )
        """,
        """
        -- 3. participant_units table
        CREATE TABLE IF NOT EXISTS participant_units (
            unit_case_id VARCHAR(64) PRIMARY KEY,
            participant_id VARCHAR(64) REFERENCES participants(participant_id) ON DELETE CASCADE,
            character_id VARCHAR(64),
            tier SMALLINT,
            rarity SMALLINT,
            item_1_id VARCHAR(100),
            item_2_id VARCHAR(100),
            item_3_id VARCHAR(100)
        )
        """,
        """
        -- 4. participant_traits table
        CREATE TABLE IF NOT EXISTS participant_traits (
            trait_case_id VARCHAR(64) PRIMARY KEY,
            participant_id VARCHAR(64) REFERENCES participants(participant_id) ON DELETE CASCADE,
            trait_name VARCHAR(64),
            num_units SMALLINT,
            tier_current SMALLINT,
            tier_total SMALLINT,
            style SMALLINT
        )
        """
    )
    
    conn = None
    try:
        conn = db_connect()
        cur = conn.cursor()
        for command in commands:
            cur.execute(command)
        conn.commit()
        print("TFT SQL Schema creation complete!")
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Error: {error}")
    finally:
            conn.close()
            cur.close()


def delete_old_matches(days=7):
    """Delete matches older than `days` days along with their child rows from participants, 
    participant_units, and participant_traits tables."""
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM matches
            WHERE game_datetime < NOW() - INTERVAL '1 day' * %s;
        """, (days,))
        deleted = cur.rowcount
        conn.commit()
        logging.info(f"Deleted {deleted} matches older than {days} days.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Error deleting old matches: {e}")
    finally:
        cur.close()
        conn.close()