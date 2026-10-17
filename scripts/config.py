"""Channel configuration for Roz-ier. Edit here, not in the build script."""

API_BASE = "https://pcc.api.espn.com/video/api/airings"

# Channels that are monitored and shown. slug -> display name (None = same as slug).
MONITORED = {
    "fast_channel_20_20": None,
    "fast_channel_according_to_jim": None,
    "fast_channel_alias": None,
    "fast_channel_ally_mcbeal": None,
    "fast_channel_arrested_development": None,
    "fast_channel_batman": None,
    "fast_channel_blackish": None,
    "fast_channel_blossom": None,
    "fast_channel_buffy_the_vampire_slayer": None,
    "fast_channel_car_chases": None,
    "fast_channel_cougar_town": None,
    "fast_channel_dharma_and_greg": None,
    "fast_channel_extreme_makeover_home_edition": None,
    "fast_channel_fresh_off_the_boat": None,
    "fast_channel_general_hospital": None,
    "fast_channel_home_improvement": None,
    "fast_channel_life_below_zero": None,
    "fast_channel_locked_up_abroad": None,
    "fast_channel_my_wife_and_kids": None,
    "fast_channel_nat_geo_animals": None,
    "fast_channel_nat_geo_history": None,
    "fast_channel_nat_geo_sharks": "fast_channel_nat_geo_predators",
    "fast_nat_geo_travel": "fast_channel_nat_geo_travel",
    "fast_channel_nypd_blue": None,
    "fast_channel_press_your_luck_and_match_game": None,
    "fast_channel_scrubs": None,
    "fast_channel_shark_tank": None,
    "fast_channel_supernanny": None,
    "fast_channel_the_100000_pyramid": None,
    "fast_channel_the_bernie_mac_show": None,
    "fast_channel_the_incredible_dr_pol": None,
    "fast_channel_the_mary_tyler_moore_show": None,
    "fast_channel_the_ocho": None,
    "fast_channel_the_practice": None,
    "fast_channel_to_catch_a_smuggler": None,
    "fast_channel_who_wants_to_be_a_millionaire": None,
    "fast_channel_wicked_tuna": None,
    "fast_channel_wipeout": None,
    "fast_channel_90s_hits": "fast_channel_felicity",
}

# Normally empty channels. Listed as "not monitored" unless they return a schedule,
# in which case they are treated as monitored.
INACTIVE = [
    "fast_channel_25_days_of_christmas",
    "fast_channel_angel",
    "fast_channel_cesar_millan",
    "fast_channel_lost_treasure",
    "fast_channel_nat_geo_jaws_claws",
    "fast_channel_nat_geo_space",
    "fast_channel_nat_geo_survival",
    "fast_channel_newhart",
    "fast_channel_press_your_luck",
    "fast_channel_the_x_files",
    "fast_channel_to_tell_the_truth",
    "fast_channel_true_crime_stories",
    "fast_channel_wife_swap",
]

# Suppressed everywhere: never fetched, shown or counted.
SUPPRESSED = ["fast_channel_on_the_red_carpet", "fast_channel_otv_true_crime"]

# Shown on the site but left out of the emailed summary.
EMAIL_EXCLUDE = ["fast_channel_the_ocho", "fast_channel_car_chases"]

RED_DAYS = 14
GREEN_DAYS = 30
GRID_DAYS_AHEAD = 29  # grid covers today through today + this many days

GAP_TOLERANCE_MIN = 10   # ignore gaps shorter than this (minutes) between airings
GAP_HORIZON_DAYS = 30    # look this far ahead for empty stretches
HEADSUP_DAYS = 10        # "enters red zone" warning looks this far ahead

# Where the previously published site lives (used to carry the history file forward between runs).
BASE_URL = "https://rbettendorf.github.io/rozierstatus"
HISTORY_KEEP_DAYS = 30
TREND_MIN_DAYS = 0.04    # ignore runway changes smaller than ~1 hour
