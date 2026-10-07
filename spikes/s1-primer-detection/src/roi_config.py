"""Single source of truth for the four ROI *roles* detection logic depends
on, and their fallback coordinates for the standalone debug entry points
below (extract_templates.py, verify_alignment.py, detector_v3.py's __main__
block, and the test suite's synthetic frames).

The live Pi runtime (main.py) never reads ROIS for coordinates -- it builds
those from the setup app's config.json via config_adapter.build_rois(). But
analyze_frame()'s MISLOAD/ABOUT_TO_FAIL condition logic still needs to know
*which* of the operator's configured ROI ids plays each of these four roles,
so it imports the ROLE_* constants below instead of hardcoding an ROI id
string inline. If an ROI is renamed in the setup app, this is the one file
that needs to change to match -- not detector_v3.py's condition logic.
"""

# ROI ids as currently named in the setup app's config (2026-09-06). Update
# these four if the operator renames the corresponding ROI in the config UI.
ROLE_SWAGE       = "Swage"
ROLE_NECK_EXPAND = "Flare"
ROLE_PRIMER_1    = "Pocket4"
ROLE_PRIMER_2    = "Pocket2"

# Fallback coordinates for standalone scripts that don't load a real
# config.json (debug entry points + test fixtures). Kept in sync with the
# live setup app's calibration as of 2026-09-06.
ROIS = {
    ROLE_SWAGE:       (28, 148, 121, 257),
    ROLE_NECK_EXPAND: (496, 40, 620, 138),
    ROLE_PRIMER_1:    (420, 270, 491, 326),
    ROLE_PRIMER_2:    (213, 314, 285, 369),
}
