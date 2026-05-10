'''
Home for our Riot API Functions.
'''

import requests, time, logging
from src.config import sleeptime

# ------------------------------- URL BUILDER FOR LEAGUES  ------------------------------ #

# LEAGUES URL BUILDER: Build up the API request URL to Riot using our config variables to get info from chall, GM, master leagues
def league_url_builder(region,tier,queue,api_key):
    api_url = (
        "https://" +
        region +
        ".api.riotgames.com/tft/league/v1/" +
        tier +
        "?queue=" +
        queue +
        "&api_key=" +
        api_key
    )
    return api_url


# ------------------------------------ REGION MAPPER  ----------------------------------- #
# Some of Riot's API URLs require a continental region (Asia), and not the specific region (KR). We map this to simplify.
continent_map = {
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe",
    "kr": "asia", "jp1": "asia",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea"
}


# --------------------------------- API REQUEST HANDLER  -------------------------------- #
# Makes an API request to Riot and deals with rate limits.
def api_request(api_url):
    while True:  # continues until the if statement is NOT hit
        try:
            # Make the request
            response = requests.get(api_url)

            # If rate limit hit (error code 429), sleep for 10 seconds
            if response.status_code == 429:
                print(f"Rate limit hit! Sleeping for {sleeptime} seconds.")
                time.sleep(sleeptime)
                continue

            return response.json()

        except requests.exceptions.RequestException as e:
            logging.error(f"API request error: {e}")
            return None